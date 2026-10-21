"""Motor de dosagem (sem dependências do HA).

Base de cálculo, com produtos Genco:

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

PRODUCT_ALK_UP = "pH Certo"
PRODUCT_PH_UP = "pH Mais"
PRODUCT_PH_DOWN = "pH Menos"
PRODUCT_CHLORINE = "Cloro granulado"

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

# Quanto esperar antes de medir de novo, segundo os rótulos Genco:
# pH Mais: testar o pH 1 h depois; pH Menos e pH Certo: reanalisar no dia seguinte;
# cloro: analisar o residual antes da próxima aplicação diária.
REMEASURE_HOURS = {
    PRODUCT_PH_UP: 1,
    PRODUCT_ALK_UP: 24,
    PRODUCT_PH_DOWN: 24,
    PRODUCT_CHLORINE: 24,
}

ALK_UP_G_PER_M3_PER_PPM = 1.7
ALK_DOWN_ML_PER_M3_PER_PPM = 1.0
PH_DOWN_ML_PER_M3_MILD = 10.0  # pH até 8,0
PH_DOWN_ML_PER_M3_STRONG = 20.0  # pH acima de 8,0
ACID_MAX_ML_PER_M3_PER_APPLICATION = 20.0
SODA_ASH_G_PER_MOL = 105.99
DICHLOR_AVAILABLE_CHLORINE = 0.56


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

    def amount_for(self, product: str) -> float:
        return sum(r.amount for r in self.recommendations if r.product == product)


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
# Tabela do rótulo do pH Mais (barrilha) Genco: g/m³ para elevar o pH a 7,5
# ---------------------------------------------------------------------------
PH_UP_LABEL_TARGET = 7.5
PH_UP_LABEL_ALK = (80.0, 120.0)
PH_UP_LABEL = (  # (pH atual, g/m³ com alcalinidade 80, g/m³ com alcalinidade 120)
    (6.4, 46.0, 74.0),
    (6.6, 38.0, 61.0),
    (6.8, 30.0, 48.0),
    (7.0, 21.0, 34.0),
    (7.2, 13.0, 21.0),
    (PH_UP_LABEL_TARGET, 0.0, 0.0),  # na meta não há dose
)


def _interp_ph(ph: float, column: int) -> float:
    """Interpola (ou extrapola nas pontas) a dose da tabela para um pH."""
    pts = [(row[0], row[column]) for row in PH_UP_LABEL]
    if ph >= pts[-1][0]:
        return 0.0
    if ph <= pts[0][0]:
        (x0, y0), (x1, y1) = pts[0], pts[1]
    else:
        for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
            if x0 <= ph <= x1:
                break
    return y0 + (y1 - y0) * (ph - x0) / (x1 - x0)


def label_ph_up_g_per_m3(alk_ppm: float, ph_now: float) -> float:
    """Dose de pH Mais (g/m³) da tabela Genco para chegar a pH 7,5.

    Interpola entre as colunas de alcalinidade 80 e 120 ppm (e extrapola
    linearmente fora delas) e entre as linhas de pH.
    """
    low = _interp_ph(ph_now, 1)
    high = _interp_ph(ph_now, 2)
    a0, a1 = PH_UP_LABEL_ALK
    value = low + (high - low) * (alk_ppm - a0) / (a1 - a0)
    return max(value, 0.0)


def ph_up_g_per_m3(
    alk_ppm: float, ph_now: float, ph_target: float, temp_c: float = 25.0
) -> float:
    """Dose de pH Mais (g/m³): tabela do rótulo, ajustada se a meta não for 7,5."""
    base = label_ph_up_g_per_m3(alk_ppm, ph_now)
    if abs(ph_target - PH_UP_LABEL_TARGET) < 1e-9 or base <= 0:
        return base
    ref = soda_ash_grams_per_m3(alk_ppm, ph_now, PH_UP_LABEL_TARGET, temp_c)
    alt = soda_ash_grams_per_m3(alk_ppm, ph_now, ph_target, temp_c)
    if ref <= 0:
        return base
    return base * alt / ref


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
def _alkalinity(volume: float, alk: float | None, t: Targets) -> Recommendation:
    if alk is None:
        return _unknown("alcalinidade")
    if alk < t.alk_min:
        total = _round_amount((t.alk_target - alk) * ALK_UP_G_PER_M3_PER_PPM * volume)
        return Recommendation(
            "alcalinidade",
            STATUS_LOW,
            f"Adicionar {_fmt(total, 'g')} de {PRODUCT_ALK_UP}",
            PRODUCT_ALK_UP,
            total,
            "g",
        )
    if alk > t.alk_max:
        total = _round_amount((alk - t.alk_target) * ALK_DOWN_ML_PER_M3_PER_PPM * volume)
        max_single = ACID_MAX_ML_PER_M3_PER_APPLICATION * volume
        apps = max(1, math.ceil(total / max_single)) if max_single else 1
        message = f"Adicionar {_fmt(total, 'ml')} de {PRODUCT_PH_DOWN}"
        note = None
        if apps > 1:
            part = _round_amount(total / apps)
            message += f" em {apps} aplicações de {_fmt(part, 'ml')}, uma por dia"
            note = "Uma aplicação por dia: reanalise no dia seguinte e repita se preciso (rótulo)."
        return Recommendation(
            "alcalinidade", STATUS_HIGH, message, PRODUCT_PH_DOWN, total, "ml", apps, note
        )
    return Recommendation("alcalinidade", STATUS_OK, "Alcalinidade OK")


def _ph(
    volume: float,
    alk: float | None,
    ph: float | None,
    alk_rec: Recommendation,
    t: Targets,
    temp_c: float,
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
        per_m3 = PH_DOWN_ML_PER_M3_MILD if ph <= 8.0 else PH_DOWN_ML_PER_M3_STRONG
        total = _round_amount(per_m3 * volume)
        return Recommendation(
            "ph",
            STATUS_HIGH,
            f"Adicionar {_fmt(total, 'ml')} de {PRODUCT_PH_DOWN}",
            PRODUCT_PH_DOWN,
            total,
            "ml",
        )
    # pH baixo
    if alk is None:
        return Recommendation(
            "ph", STATUS_BLOCKED, "Informe a alcalinidade para calcular o pH Mais"
        )
    per_m3 = ph_up_g_per_m3(alk, ph, t.ph_target, temp_c) * t.ph_up_factor
    total = _round_amount(per_m3 * volume)
    return Recommendation(
        "ph",
        STATUS_LOW,
        f"Adicionar {_fmt(total, 'g')} de {PRODUCT_PH_UP}",
        PRODUCT_PH_UP,
        total,
        "g",
        note="Dose da tabela do rótulo Genco; teste o pH 1 h depois da aplicação.",
    )


def _chlorine(
    volume: float, cl: float | None, ph: float | None, t: Targets
) -> Recommendation:
    if cl is None:
        return _unknown("cloro")
    if cl < t.cl_min:
        total = _round_amount(
            (t.cl_target - cl) * volume / DICHLOR_AVAILABLE_CHLORINE
        )
        note = None
        if ph is not None and ph > t.ph_max:
            note = "pH alto reduz a eficácia do cloro; corrija o pH também."
        return Recommendation(
            "cloro",
            STATUS_LOW,
            f"Adicionar {_fmt(total, 'g')} de cloro granulado (dicloro)",
            PRODUCT_CHLORINE,
            total,
            "g",
            note=note,
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
) -> Analysis:
    """Analisa as medições e devolve as recomendações."""
    t = targets or Targets()
    temp = 25.0 if temp_c is None else min(max(temp_c, 5.0), 40.0)

    alk_rec = _alkalinity(volume_m3, alkalinity, t)
    ph_rec = _ph(volume_m3, alkalinity, ph, alk_rec, t, temp)
    cl_rec = _chlorine(volume_m3, chlorine, ph, t)
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
