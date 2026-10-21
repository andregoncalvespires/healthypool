"""Produtos de manutenção e instruções de aplicação.

Sem dependências do HA. Dados dos rótulos Genco:

* Algicida de Manutenção: 5 mL/m³ por semana; pH 7,4 a 7,6; cloro livre 2 a 4 ppm;
  nunca junto com cloro, com pelo menos 12 h entre eles; piscina liberada após 30 min.
* Algicida de Choque (água verde com algas; íons de cobre quelados): 7 mL/m³ quando
  necessário; mesmas regras de cloro; escovar e aspirar quando as algas morrerem;
  repetir se restarem sinais (o rótulo do de manutenção cita uso semanal do choque).
* Clarificante Genfloc: preventivo 1,5 mL/m³ por semana (filtrar 1 a 2 h);
  corretivo 3 a 6 mL/m³ em dose única para água turva (filtrar 6 a 8 h).
* Removedor de metais Genquest: 15 mL/m³ por ppm de metal (ferro, manganês, cobre) ou
  50 mL/m³ para eliminar manchas/coloração; cloro livre no máximo 1 ppm durante e até
  7 dias depois, sem oxidação de choque; pH 7,4 a 7,6 e alcalinidade 80 a 120 ppm;
  aplicar à noite ou ao fim da tarde; repetir após 1 semana se persistir.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from .catalog import (
    ROLE_ALGAECIDE,
    ROLE_CHLORINE,
    ROLE_CLARIFIER,
    ROLE_METALS,
    Product,
    ProductSet,
    default_products,
    render,
)
from .dosing import STATUS_BLOCKED, Analysis

ASPECT_CLEAR = "Limpa"
ASPECT_CLOUDY = "Turva"
ASPECT_GREEN = "Verde (algas)"
ASPECT_METALS = "Verde transparente (metais)"
ASPECT_STAINS = "Manchas coloridas (metais)"
ASPECTS = (ASPECT_CLEAR, ASPECT_CLOUDY, ASPECT_GREEN, ASPECT_METALS, ASPECT_STAINS)
METAL_ASPECTS = (ASPECT_METALS, ASPECT_STAINS)
# Valores salvos por versões anteriores
LEGACY_ASPECTS = {"Verde": ASPECT_GREEN}

KEY_ALGAECIDE = ROLE_ALGAECIDE
KEY_CLARIFIER = ROLE_CLARIFIER
KEY_CHLORINE = ROLE_CHLORINE
KEY_METALS = ROLE_METALS

DEFAULT_PH_WINDOW = (7.4, 7.6)
DEFAULT_CHLORINE_GAP_HOURS = 12.0
DEFAULT_METALS_MAX_CHLORINE = 1.0


def ph_window(product: Product) -> tuple[float, float]:
    """Faixa de pH exigida pela ficha do produto (algicida e removedor de metais)."""
    window = product.rules.get("ph_window") or DEFAULT_PH_WINDOW
    return float(window[0]), float(window[1])


def chlorine_gap_hours(algaecide: Product) -> float:
    """Horas entre algicida e cloro (nos dois sentidos)."""
    return float(algaecide.rules.get("min_hours_between_chlorine", DEFAULT_CHLORINE_GAP_HOURS))


def metals_max_chlorine(metals: Product) -> float:
    return float(metals.rules.get("max_chlorine", DEFAULT_METALS_MAX_CHLORINE))


def _br(value: float) -> str:
    """Número no formato brasileiro, sem zeros à toa (7,4; 12)."""
    return f"{value:g}".replace(".", ",")


ITEM_OK = "ok"
ITEM_DUE = "due"
ITEM_WAIT = "wait"
ITEM_BLOCKED = "blocked"


@dataclass
class MaintenanceItem:
    """Situação de um produto de manutenção."""

    key: str
    name: str
    mode: str
    status: str
    message: str
    amount_ml: float = 0.0
    interval_days: float = 0.0
    last_applied: datetime | None = None
    next_due: datetime | None = None
    wait_until: datetime | None = None
    notes: list[str] = field(default_factory=list)
    blocked_by: str | None = None  # "ph", "alkalinity" ou "chlorine" quando status = blocked

    @property
    def pending(self) -> bool:
        return self.status != ITEM_OK


def fmt_dt(value: datetime, reference: datetime) -> str:
    local = value.astimezone(reference.tzinfo) if reference.tzinfo else value
    return local.strftime("%d/%m %H:%M")


def _ph_block_message(ph: float, what: str, product: Product, acid: Product | None = None) -> str:
    low, high = ph_window(product)
    message = f"Ajuste o pH para {_br(low)} a {_br(high)} antes de {what}"
    min_ph = acid.dosing.get("label_min_ph") if acid else None
    if ph > high and min_ph is not None:
        message += f" (o rótulo do {acid.name} só traz dose a partir de pH {_br(float(min_ph))})"
    return message


def _round_ml(value: float) -> float:
    return float(round(value / 5.0) * 5) if value >= 50 else float(round(value))


def metals_window_end(
    last_applied: datetime | None, now: datetime, product: Product | None = None
) -> datetime | None:
    """Fim da janela (cloro limitado e sem choque) depois do removedor de metais."""
    if last_applied is None:
        return None
    product = product or default_products().metals
    days = float(product.dosing.get("window_days", 7))
    end = last_applied + timedelta(days=days)
    return end if now < end else None


def _phrase(name: str) -> str:
    """Nome em minúsculas dentro de uma frase, preservando o "pH"."""
    return name if name[:2] == "pH" else name.lower()


def evaluate_algaecide(
    volume_m3: float,
    aspect: str,
    last_applied: datetime | None,
    last_chlorine: datetime | None,
    ph: float | None,
    chlorine: float | None,
    now: datetime,
    interval_days: float,
    chlorine_limited: bool = False,
    product: Product | None = None,
    acid: Product | None = None,
    metals: Product | None = None,
) -> MaintenanceItem:
    P = default_products()
    product = product or P.algaecide
    acid = acid or P.acid
    metals = metals or P.metals
    d = product.dosing
    green = aspect == ASPECT_GREEN
    name = d.get("shock_name", f"{product.name} de choque") if green else d.get(
        "maintenance_name", f"{product.name} de manutenção"
    )
    mode = "choque" if green else "manutenção"
    per_m3 = float(d["shock_ml_per_m3"] if green else d["maintenance_ml_per_m3"])
    interval = float(d.get("shock_interval_days", 7) if green else interval_days)
    amount = _round_ml(per_m3 * volume_m3)
    low_ph, high_ph = ph_window(product)
    gap = chlorine_gap_hours(product)
    cl_low, cl_high = (float(x) for x in product.rules.get("chlorine_range", (2, 4)))

    notes = [
        f"Nunca aplique junto com cloro: deixe pelo menos {_br(gap)} h entre os dois.",
        f"Mantenha o cloro livre entre {_br(cl_low)} e {_br(cl_high)} ppm.",
    ]
    if chlorine_limited:
        window_days = float(metals.dosing.get("window_days", 7))
        notes[1] = (
            f"Conflito entre rótulos: o algicida pede cloro de {_br(cl_low)} a {_br(cl_high)} ppm, mas o "
            f"removedor de metais exige no máximo {_br(metals_max_chlorine(metals))} ppm até "
            f"{_br(window_days)} dias depois da aplicação. Não eleve o cloro agora."
        )
    if green:
        notes.append("Mantenha a filtração por 30 a 60 min para homogeneizar a solução.")
        notes.append("Quando as algas morrerem (ficam marrons), escove e aspire. Repita se restarem sinais.")
        if product.rules.get("shock_contains_copper"):
            notes.append("O algicida de choque é à base de íons de cobre: não use se a cor verde for de metais.")
    else:
        notes.append("Aspire o fundo pelo menos 2 vezes por semana.")
    notes.extend(product.notes)

    next_due = last_applied + timedelta(days=interval) if last_applied else None
    item = MaintenanceItem(
        KEY_ALGAECIDE, name, mode, ITEM_OK, "", 0.0, interval, last_applied, next_due, None, notes
    )

    if last_applied is not None and now < next_due:
        item.message = f"{name} em dia. Próxima aplicação: {fmt_dt(next_due, now)}"
        return item

    item.amount_ml = amount
    wait_until = None
    if last_chlorine is not None:
        gap_end = last_chlorine + timedelta(hours=gap)
        if now < gap_end:
            wait_until = gap_end

    if ph is not None and not low_ph <= ph <= high_ph:
        item.status = ITEM_BLOCKED
        item.blocked_by = "ph"
        item.message = _ph_block_message(ph, f"aplicar o {name.lower()}", product, acid)
    elif wait_until is not None:
        item.status = ITEM_WAIT
        item.wait_until = wait_until
        item.message = (
            f"Aguardar até {fmt_dt(wait_until, now)} ({_br(gap)} h após o cloro) "
            f"para aplicar {int(amount)} mL de {name.lower()}"
        )
    else:
        item.status = ITEM_DUE
        item.message = f"Adicionar {int(amount)} mL de {name.lower()}"
        if chlorine is not None and not cl_low <= chlorine <= cl_high and not chlorine_limited:
            item.notes.insert(
                0,
                f"O cloro livre está fora de {_br(cl_low)} a {_br(cl_high)} ppm; corrija-o (em outro horário).",
            )
    return item


def evaluate_clarifier(
    volume_m3: float,
    aspect: str,
    last_applied: datetime | None,
    now: datetime,
    interval_days: float,
    product: Product | None = None,
) -> MaintenanceItem:
    product = product or default_products().clarifier
    d = product.dosing
    corrective = aspect in (ASPECT_CLOUDY, ASPECT_GREEN)
    name = f"{product.name} corretivo" if corrective else f"{product.name} preventivo"
    mode = "corretivo" if corrective else "preventivo"
    per_m3 = float(d["corrective_ml_per_m3"] if corrective else d["preventive_ml_per_m3"])
    interval = float(d.get("corrective_interval_days", 1) if corrective else interval_days)
    amount = _round_ml(per_m3 * volume_m3)
    filtering = d.get("corrective_filter_hours", "6 a 8 h") if corrective else d.get(
        "preventive_filter_hours", "1 a 2 h"
    )

    notes = [
        "Faça a retrolavagem do filtro se necessário e ligue a filtração.",
        "Dilua a dose em um balde com água e espalhe a solução pela superfície da piscina.",
        f"Mantenha a filtração por {filtering} e depois aspire a sujeira decantada.",
        "Não substitui cloro nem controle do pH.",
        *product.notes,
    ]
    next_due = last_applied + timedelta(days=interval) if last_applied else None
    item = MaintenanceItem(
        KEY_CLARIFIER, name, mode, ITEM_OK, "", 0.0, interval, last_applied, next_due, None, notes
    )
    if last_applied is not None and now < next_due:
        item.message = f"{name} em dia. Próxima aplicação: {fmt_dt(next_due, now)}"
        return item
    item.amount_ml = amount
    item.status = ITEM_DUE
    item.message = f"Adicionar {int(amount)} mL de {name.lower()}"
    return item


def evaluate_metals(
    volume_m3: float,
    aspect: str,
    last_applied: datetime | None,
    alkalinity: float | None,
    ph: float | None,
    chlorine: float | None,
    metals_ppm: float | None,
    now: datetime,
    alk_min: float = 80.0,
    alk_max: float = 120.0,
    product: Product | None = None,
    acid: Product | None = None,
) -> MaintenanceItem:
    """Removedor de metais: só entra em ação com aspecto de metais."""
    P = default_products()
    product = product or P.metals
    acid = acid or P.acid
    d = product.dosing
    name = product.item_name
    window_days = float(d.get("window_days", 7))
    repeat_days = float(d.get("repeat_days", 7))
    max_cl = metals_max_chlorine(product)
    window_end = metals_window_end(last_applied, now, product)
    repeat_at = last_applied + timedelta(days=repeat_days) if last_applied else None
    item = MaintenanceItem(
        KEY_METALS, name, "inativo", ITEM_OK, "", 0.0, repeat_days, last_applied, repeat_at
    )

    if aspect not in METAL_ASPECTS:
        if window_end is not None:
            item.mode = "em ação"
            item.message = (
                f"{name} em ação até {fmt_dt(window_end, now)}: "
                f"cloro no máximo {_br(max_cl)} ppm e sem choque"
            )
        else:
            item.message = "Não necessário (sem sinais de metais na água)"
        return item

    stains = aspect == ASPECT_STAINS
    ppm = float(metals_ppm) if metals_ppm else 0.0
    per_ppm = float(d["ml_per_m3_per_ppm"])
    removal = float(d["removal_ml_per_m3"])
    per_m3 = per_ppm * ppm if ppm > 0 else removal
    amount = _round_ml(per_m3 * volume_m3)
    item.mode = "tratamento"
    low_ph, high_ph = ph_window(product)

    notes: list[str] = []
    if aspect == ASPECT_METALS:
        notes.append("Água verde e transparente sugere metais pela aparência. Só o resultado confirma: reavalie a cor após 7 dias.")
        notes.append("Fontes possíveis de metais: água de poço (o removedor de metais é indicado para piscinas abastecidas assim) e o algicida de choque, se contiver íons de cobre.")
    if ppm > 0:
        notes.append(f"Dose do rótulo: {_br(per_ppm)} mL/m³ por ppm de metal ({ppm:g} ppm informados).")
    else:
        notes.append(f"Dose de eliminação do rótulo: {_br(removal)} mL/m³.")
    bottle_ml = float(d.get("bottle_ml", 0) or 0)
    if bottle_ml > 0:
        bottles = amount / bottle_ml
        notes.append(
            f"O frasco tem {_br(bottle_ml / 1000)} L: esta dose equivale a {bottles:.1f} frasco(s).".replace(".", ",")
        )
    notes += [
        "Aplique de preferência à noite ou ao fim da tarde, sobre o bocal de retorno, com a filtração ligada.",
        f"Mantenha o cloro livre em no máximo {_br(max_cl)} ppm e não faça oxidação de choque por {_br(window_days)} dias.",
        "Funcione a filtração diariamente"
        + (" e retrolave o filtro todo dia enquanto durar o tratamento." if stains else "."),
    ]
    if stains:
        notes.append("Escove as manchas com frequência por 5 a 7 dias.")
    notes.append("Turbidez depois da aplicação é temporária. Aguarde 1 h para usar a piscina.")
    notes.extend(product.notes)
    item.notes = notes

    if last_applied is not None and now < repeat_at:
        item.message = (
            f"{name} aplicado em {fmt_dt(last_applied, now)}. "
            f"Reavalie a cor em {fmt_dt(repeat_at, now)}; se persistir, repita"
        )
        return item

    item.amount_ml = amount
    if alkalinity is not None and not alk_min <= alkalinity <= alk_max:
        item.status = ITEM_BLOCKED
        item.blocked_by = "alkalinity"
        item.message = f"Ajuste a alcalinidade para {alk_min:g} a {alk_max:g} ppm antes do {name.lower()}"
    elif ph is not None and not low_ph <= ph <= high_ph:
        item.status = ITEM_BLOCKED
        item.blocked_by = "ph"
        item.message = _ph_block_message(ph, f"o {name.lower()}", product, acid)
    elif chlorine is not None and chlorine > max_cl:
        item.status = ITEM_BLOCKED
        item.blocked_by = "chlorine"
        item.message = (
            f"Aguarde o cloro baixar a no máximo {_br(max_cl)} ppm antes do {name.lower()} "
            "(não adicione cloro)"
        )
    else:
        item.status = ITEM_DUE
        item.message = f"Adicionar {int(amount)} mL de {name.lower()}"
        if chlorine is None:
            item.notes.insert(
                0, f"Confirme que o cloro livre está em no máximo {_br(max_cl)} ppm antes de aplicar."
            )
    return item


# ---------------------------------------------------------------------------
# Instruções de aplicação
# ---------------------------------------------------------------------------
def _release_text(products: ProductSet) -> str:
    """Quando liberar a piscina, conforme as fichas dos produtos escolhidos."""
    groups: dict[float, list[str]] = {}
    for role in ("ph_up", "acid", "algaecide", "clarifier", "metals_remover"):
        product = products[role]
        minutes = float(product.rules.get("release_minutes", 30))
        groups.setdefault(minutes, []).append(_phrase(product.item_name))
    parts = []
    for minutes in sorted(groups):
        when = f"{minutes / 60:g} h" if minutes % 60 == 0 else f"{minutes:g} min"
        names = groups[minutes]
        who = ", ".join(names[:-1]) + (" e " if len(names) > 1 else "") + names[-1]
        if len(names) == 1 and names[0][:2] != "pH":
            who = f"o {who}"
        parts.append(f"{when} após {who}")
    limit = products.chlorine.rules.get("release_max_chlorine")
    if limit is not None:
        parts.append(f"com cloro, só com o residual abaixo de {_br(float(limit))} ppm")
    return "Liberação da piscina: " + "; ".join(parts) + "."


def build_instructions(
    analysis: Analysis,
    algaecide: MaintenanceItem,
    clarifier: MaintenanceItem,
    metals: MaintenanceItem,
    now: datetime,
    products: ProductSet | None = None,
) -> tuple[str, int]:
    """Monta o texto em Markdown com a ordem e o modo de aplicação.

    Retorna (markdown, quantidade de aplicações pendentes).
    """
    P = products or default_products()
    steps: list[tuple[str, str, list[str]]] = []  # (título, linha da ordem, instruções)
    warnings: list[str] = []
    for rec in analysis.recommendations:
        if rec.actionable and rec.product and rec.amount > 0:
            qty = f"{int(round(rec.amount))} {rec.unit}"
            line = f"{rec.product}: {qty}"
            if rec.applications > 1:
                line += f" em {rec.applications} aplicações de {int(round(rec.per_application))} {rec.unit}, uma por dia"
            how = [render(t, P) for t in P[rec.role].instructions] if rec.role else []
            steps.append((rec.product, line, how))
        elif rec.status == STATUS_BLOCKED:
            steps.append((rec.parameter, rec.message, []))
        elif rec.actionable:
            warnings.append(rec.message)

    for item in (metals, algaecide, clarifier):
        if item.pending:
            steps.append((item.name, item.message, list(item.notes)))

    if not steps and not warnings:
        return "Nenhuma aplicação pendente.", 0

    lines: list[str] = []
    if steps:
        lines.append("**Ordem de aplicação**")
        for i, (_, order_line, _) in enumerate(steps, 1):
            lines.append(f"{i}. {order_line}")
        lines.append("")
        lines.append("**Como aplicar**")
        for title, _, how in steps:
            if not how:
                continue
            lines.append(f"- *{title}*")
            lines.extend(f"  - {h}" for h in how)
        lines.append("")
    else:
        lines.append("Nenhuma aplicação pendente.")
        lines.append("")
    if warnings:
        lines.append("**Atenção**")
        lines.extend(f"- {w}" for w in warnings)
        lines.append("")
    lines.append(_release_text(P))
    return "\n".join(lines), len(steps)
