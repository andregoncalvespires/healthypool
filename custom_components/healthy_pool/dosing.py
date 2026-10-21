"""Motor de dosagem (sem dependências do HA).

Base de cálculo, com produtos Genco:

As taxas vêm das fichas dos produtos (``catalog.py`` e ``products/*.json``). Com os produtos
Genco padrão:

* Alcalinidade baixa -> pH Certo (bicarbonato de sódio): 1,7 g/m³ para cada 1 ppm
  (rótulo: 17 g/m³ elevam 10 ppm).
* Alcalinidade alta -> pH Menos (ácido líquido): 1 ml/m³ para cada 1 ppm
  (rótulo: 10 ml/m³ a cada 10 ppm).
* pH alto -> pH Menos: 10 ml/m³ (pH 7,8 a 8,0) ou 20 ml/m³ (pH acima de 8,0),
  conforme o rótulo.
* pH baixo -> pH Mais (barrilha): tabela do rótulo Genco (dose para chegar a
  pH 7,5 conforme pH atual e alcalinidade de 80 ou 120 ppm), interpolada para
  valores intermediários. O cálculo pelo equilíbrio do carbonato fica só como
  referência para ajustar a dose quando a meta de pH não é 7,5.
* Cloro baixo -> cloro granulado estabilizado (dicloro, 56 % de cloro
  disponível): 1 ppm de cloro livre = 1 g/m³ de cloro disponível.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from .catalog import (
    ROLE_ACID,
    ROLE_ALK_UP,
    ROLE_CHLORINE,
    ROLE_PH_UP,
    Product,
    ProductSet,
    default_products,
)

STATUS_OK = "ok"
STATUS_LOW = "low"
STATUS_HIGH = "high"
STATUS_BLOCKED = "blocked"
STATUS_PENDING = "pending"
STATUS_UNKNOWN = "unknown"

OVERALL_OK = "Água OK"
OVERALL_TREAT = "Tratar Água"
OVERALL_PENDING = "Aguardando nova medição"
OVERALL_INCOMPLETE = "Medição incompleta"
OVERALL_NO_DATA = "Sem medição"

SODA_ASH_G_PER_MOL = 105.99


@dataclass(frozen=True)
class Targets:
    """Faixas aceitáveis e metas de correção."""

    alk_min: float = 80.0
    alk_target: float = 100.0
    alk_max: float = 120.0
    ph_min: float = 7.2
    ph_target: float = 7.5
    ph_max: float = 7.8
    cl_min: float = 2.0
    cl_target: float = 3.0
    cl_max: float = 4.0
    ph_up_factor: float = 1.0


@dataclass
class Recommendation:
    """Recomendação para um parâmetro."""

    parameter: str
    status: str
    message: str
    product: str | None = None
    amount: float = 0.0  # quantidade total
    unit: str | None = None
    applications: int = 1
    note: str | None = None
    role: str | None = None  # função do produto (ver catalog.py)

    @property
    def per_application(self) -> float:
        return self.amount / self.applications if self.applications else self.amount

    @property
    def actionable(self) -> bool:
        return self.status in (STATUS_LOW, STATUS_HIGH, STATUS_BLOCKED)


@dataclass
class Analysis:
    """Resultado completo da análise da água."""

    alkalinity: Recommendation
    ph: Recommendation
    chlorine: Recommendation
    overall: str

    @property
    def recommendations(self) -> list[Recommendation]:
        return [self.alkalinity, self.ph, self.chlorine]

    @property
    def needs_treatment(self) -> bool:
        return any(r.actionable for r in self.recommendations)

    @property
    def has_data(self) -> bool:
        return any(r.status != STATUS_UNKNOWN for r in self.recommendations)

    @property
    def next_action(self) -> str | None:
        for rec in self.recommendations:
            if rec.actionable:
                return rec.message
        return None

    def amount_for(self, role: str) -> float:
        """Quantidade total pedida para um produto, pela função (alk_up, acid, ph_up, chlorine)."""
        return sum(r.amount for r in self.recommendations if r.role == role)


# ---------------------------------------------------------------------------
# Química do carbonato
# ---------------------------------------------------------------------------
def _carbonate_constants(temp_c: float) -> tuple[float, float]:
    """K1 e K2 do ácido carbônico (Plummer & Busenberg, 1982)."""
    t = temp_c + 273.15
    pk1 = 3404.71 / t + 0.032786 * t - 14.8435
    pk2 = 2902.39 / t + 0.02379 * t - 6.4980
    return 10 ** (-pk1), 10 ** (-pk2)


def _alpha(ph: float, k1: float, k2: float) -> tuple[float, float, float]:
    h = 10 ** (-ph)
    d = h * h + k1 * h + k1 * k2
    return h * h / d, k1 * h / d, k1 * k2 / d


def _oh_minus_h(ph: float) -> float:
    return 10 ** (ph - 14.0) - 10 ** (-ph)


def soda_ash_grams_per_m3(
    alk_ppm: float, ph_now: float, ph_target: float, temp_c: float = 25.0
) -> float:
    """Gramas de barrilha (Na2CO3) por m³ para subir o pH até a meta.

    Considera sistema fechado: o carbono inorgânico total é calculado a partir da
    alcalinidade e do pH atuais; a barrilha acrescenta 2 eq de alcalinidade e
    1 mol de carbono por mol. Na prática o CO2 também escapa para o ar, então a
    dose é conservadora: reaplique só depois de medir de novo.
    """
    if ph_target <= ph_now:
        return 0.0
    k1, k2 = _carbonate_constants(temp_c)
    ta = max(alk_ppm, 1.0) / 50000.0  # eq/L (1 ppm CaCO3 = 0,02 meq/L)

    _, a1, a2 = _alpha(ph_now, k1, k2)
    dic = (ta - _oh_minus_h(ph_now)) / (a1 + 2.0 * a2)

    _, a1t, a2t = _alpha(ph_target, k1, k2)
    r_t = a1t + 2.0 * a2t
    x = (r_t * dic + _oh_minus_h(ph_target) - ta) / (2.0 - r_t)  # mol/L
    return max(x, 0.0) * 1000.0 * SODA_ASH_G_PER_MOL  # g/m³


# ---------------------------------------------------------------------------
# Tabela do rótulo do pH Mais (ficha do produto): g/m³ para elevar o pH à meta da tabela
# ---------------------------------------------------------------------------
def _table(product: Product) -> tuple[float, tuple[float, float], list[tuple[float, float, float]]]:
    d = product.dosing
    rows = [(float(r[0]), float(r[1]), float(r[2])) for r in d["table"]]
    rows.sort()
    alk = d["table_alkalinity"]
    return float(d["table_target_ph"]), (float(alk[0]), float(alk[1])), rows


def _interp_ph(ph: float, column: int, target: float, rows: list[tuple[float, float, float]]) -> float:
    """Interpola (ou extrapola nas pontas) a dose da tabela para um pH."""
    pts = [(row[0], row[column]) for row in rows] + [(target, 0.0)]  # na meta não há dose
    if ph >= pts[-1][0]:
        return 0.0
    if ph <= pts[0][0]:
        (x0, y0), (x1, y1) = pts[0], pts[1]
    else:
        for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
            if x0 <= ph <= x1:
                break
    return y0 + (y1 - y0) * (ph - x0) / (x1 - x0)


def label_ph_up_g_per_m3(alk_ppm: float, ph_now: float, product: Product | None = None) -> float:
    """Dose de pH Mais (g/m³) da tabela do produto para chegar ao pH da tabela.

    Interpola entre as colunas de alcalinidade da tabela (e extrapola linearmente fora
    delas) e entre as linhas de pH.
    """
    product = product or default_products().ph_up
    target, (a0, a1), rows = _table(product)
    low = _interp_ph(ph_now, 1, target, rows)
    high = _interp_ph(ph_now, 2, target, rows)
    value = low + (high - low) * (alk_ppm - a0) / (a1 - a0)
    return max(value, 0.0)


def ph_up_g_per_m3(
    alk_ppm: float,
    ph_now: float,
    ph_target: float,
    temp_c: float = 25.0,
    product: Product | None = None,
) -> float:
    """Dose de pH Mais (g/m³): tabela do produto, ajustada se a meta não for a da tabela."""
    product = product or default_products().ph_up
    table_target = _table(product)[0]
    base = label_ph_up_g_per_m3(alk_ppm, ph_now, product)
    if abs(ph_target - table_target) < 1e-9 or base <= 0:
        return base
    if product.dosing.get("chemistry") == "sodium_carbonate":
        ref = soda_ash_grams_per_m3(alk_ppm, ph_now, table_target, temp_c)
        alt = soda_ash_grams_per_m3(alk_ppm, ph_now, ph_target, temp_c)
        if ref <= 0:
            return base
        return base * alt / ref
    # sem modelo químico: proporcional à distância até a meta
    span = table_target - ph_now
    return base * max(ph_target - ph_now, 0.0) / span if span > 0 else base


# ---------------------------------------------------------------------------
# Utilidades
# ---------------------------------------------------------------------------
def _round_amount(value: float) -> float:
    if value >= 100:
        return float(round(value / 10.0) * 10)
    if value >= 20:
        return float(round(value / 5.0) * 5)
    return float(round(value))


def _fmt(amount: float, unit: str) -> str:
    return f"{int(round(amount))} {unit}"


def _unknown(parameter: str) -> Recommendation:
    return Recommendation(parameter, STATUS_UNKNOWN, "Sem medição")


# ---------------------------------------------------------------------------
# Regras por parâmetro
# ---------------------------------------------------------------------------
def _ph_down_rate(acid: Product, ph: float) -> float:
    """mL/m³ de ácido para pH alto, pelos degraus da ficha (up_to_ph em ordem crescente)."""
    steps = acid.dosing["ph_steps"]
    for step in steps:
        limit = step.get("up_to_ph")
        if limit is None or ph <= float(limit):
            return float(step["ml_per_m3"])
    return float(steps[-1]["ml_per_m3"])


def _alkalinity(volume: float, alk: float | None, t: Targets, P: ProductSet) -> Recommendation:
    if alk is None:
        return _unknown("alcalinidade")
    if alk < t.alk_min:
        up = P.alk_up
        rate = float(up.dosing["g_per_m3_per_ppm"])
        total = _round_amount((t.alk_target - alk) * rate * volume)
        return Recommendation(
            "alcalinidade",
            STATUS_LOW,
            f"Adicionar {_fmt(total, up.unit)} de {up.text_name}",
            up.name,
            total,
            up.unit,
            role=ROLE_ALK_UP,
        )
    if alk > t.alk_max:
        acid = P.acid
        rate = float(acid.dosing["alkalinity_ml_per_m3_per_ppm"])
        total = _round_amount((alk - t.alk_target) * rate * volume)
        max_single = float(acid.dosing["max_ml_per_m3_per_application"]) * volume
        apps = max(1, math.ceil(total / max_single)) if max_single else 1
        message = f"Adicionar {_fmt(total, 'ml')} de {acid.text_name}"
        note = None
        if apps > 1:
            part = _round_amount(total / apps)
            message += f" em {apps} aplicações de {_fmt(part, 'ml')}, uma por dia"
            note = "Uma aplicação por dia: reanalise no dia seguinte e repita se preciso (rótulo)."
        return Recommendation(
            "alcalinidade", STATUS_HIGH, message, acid.name, total, acid.unit, apps, note, ROLE_ACID
        )
    return Recommendation("alcalinidade", STATUS_OK, "Alcalinidade OK")


def _ph(
    volume: float,
    alk: float | None,
    ph: float | None,
    alk_rec: Recommendation,
    t: Targets,
    temp_c: float,
    P: ProductSet,
) -> Recommendation:
    if ph is None:
        return _unknown("ph")
    if t.ph_min <= ph <= t.ph_max:
        return Recommendation("ph", STATUS_OK, "pH OK")
    if alk_rec.status in (STATUS_LOW, STATUS_HIGH):
        return Recommendation(
            "ph", STATUS_BLOCKED, "Ajuste a alcalinidade antes de corrigir o pH"
        )
    if ph > t.ph_max:
        acid = P.acid
        per_m3 = _ph_down_rate(acid, ph)
        total = _round_amount(per_m3 * volume)
        return Recommendation(
            "ph",
            STATUS_HIGH,
            f"Adicionar {_fmt(total, 'ml')} de {acid.text_name}",
            acid.name,
            total,
            acid.unit,
            role=ROLE_ACID,
        )
    # pH baixo
    if alk is None:
        return Recommendation(
            "ph", STATUS_BLOCKED, f"Informe a alcalinidade para calcular o {P.ph_up.name}"
        )
    up = P.ph_up
    per_m3 = ph_up_g_per_m3(alk, ph, t.ph_target, temp_c, up) * t.ph_up_factor
    total = _round_amount(per_m3 * volume)
    wait = up.remeasure_hours
    retest = f"; teste o pH {wait:g} h depois da aplicação" if wait > 0 else ""
    return Recommendation(
        "ph",
        STATUS_LOW,
        f"Adicionar {_fmt(total, up.unit)} de {up.text_name}",
        up.name,
        total,
        up.unit,
        note=f"Dose da tabela do rótulo {up.brand}{retest}.",
        role=ROLE_PH_UP,
    )


def _chlorine(
    volume: float, cl: float | None, ph: float | None, t: Targets, P: ProductSet
) -> Recommendation:
    if cl is None:
        return _unknown("cloro")
    if cl < t.cl_min:
        chlorine = P.chlorine
        total = _round_amount(
            (t.cl_target - cl) * volume / float(chlorine.dosing["available_chlorine"])
        )
        note = None
        if ph is not None and ph > t.ph_max:
            note = "pH alto reduz a eficácia do cloro; corrija o pH também."
        return Recommendation(
            "cloro",
            STATUS_LOW,
            f"Adicionar {_fmt(total, chlorine.unit)} de {chlorine.text_name}",
            chlorine.name,
            total,
            chlorine.unit,
            note=note,
            role=ROLE_CHLORINE,
        )
    if cl > t.cl_max:
        return Recommendation(
            "cloro",
            STATUS_HIGH,
            "Cloro muito alto: não adicionar, aguarde baixar",
        )
    return Recommendation("cloro", STATUS_OK, "Cloro OK")


def analyze(
    volume_m3: float,
    alkalinity: float | None,
    ph: float | None,
    chlorine: float | None,
    targets: Targets | None = None,
    temp_c: float | None = None,
    treatment_pending: bool | set[str] = False,
    products: ProductSet | None = None,
) -> Analysis:
    """Analisa as medições e devolve as recomendações."""
    t = targets or Targets()
    temp = 25.0 if temp_c is None else min(max(temp_c, 5.0), 40.0)

    P = products or default_products()
    alk_rec = _alkalinity(volume_m3, alkalinity, t, P)
    ph_rec = _ph(volume_m3, alkalinity, ph, alk_rec, t, temp, P)
    cl_rec = _chlorine(volume_m3, chlorine, ph, t, P)
    recs = [alk_rec, ph_rec, cl_rec]

    if treatment_pending:
        names = ("alkalinity", "ph", "chlorine")
        for name, rec in zip(names, recs):
            handled = (
                treatment_pending is True
                or name in treatment_pending
                or (name == "ph" and "alkalinity" in treatment_pending and rec.status == STATUS_BLOCKED)
            )
            if handled and rec.actionable:
                rec.status = STATUS_PENDING
                rec.message = "Aguardando nova medição após o tratamento"
                rec.product = None
                rec.role = None
                rec.amount = 0.0
                rec.unit = None
                rec.applications = 1
                rec.note = None

    return Analysis(alk_rec, ph_rec, cl_rec, overall_status(r.status for r in recs))


def overall_status(statuses) -> str:
    """Situação geral a partir das situações de cada parâmetro."""
    statuses = list(statuses)
    if all(s == STATUS_UNKNOWN for s in statuses):
        return OVERALL_NO_DATA
    if any(s in (STATUS_LOW, STATUS_HIGH, STATUS_BLOCKED) for s in statuses):
        return OVERALL_TREAT
    if STATUS_PENDING in statuses:
        return OVERALL_PENDING
    if STATUS_UNKNOWN in statuses:
        return OVERALL_INCOMPLETE
    return OVERALL_OK


def cap_chlorine(analysis: Analysis, chlorine: float | None, cap: float, reason: str) -> None:
    """Limita o cloro (ex.: removedor de metais exige no máximo 1 ppm).

    Troca a recomendação de cloro: nunca pede para adicionar e só aponta
    problema se o cloro estiver acima do limite.
    """
    rec = analysis.chlorine
    if chlorine is None or rec.status in (STATUS_UNKNOWN, STATUS_PENDING):
        return
    if chlorine > cap:
        rec.status = STATUS_HIGH
        rec.message = f"{reason}: cloro acima de {cap:g} ppm, não adicionar cloro nem fazer choque; aguarde baixar"
    else:
        rec.status = STATUS_OK
        rec.message = f"Cloro OK para o tratamento ({reason}: máximo {cap:g} ppm)"
    rec.product = None
    rec.role = None
    rec.amount = 0.0
    rec.unit = None
    rec.applications = 1
    rec.note = (
        "Com o cloro baixo a desinfecção fica reduzida; vale limitar o uso da piscina durante o tratamento."
        if chlorine <= cap
        else None
    )
    analysis.overall = overall_status(r.status for r in analysis.recommendations)


round_amount = _round_amount  # uso público (pool.py)
