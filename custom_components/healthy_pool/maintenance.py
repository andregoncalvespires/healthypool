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

from .dosing import (
    PRODUCT_ALK_UP,
    PRODUCT_CHLORINE,
    PRODUCT_PH_DOWN,
    PRODUCT_PH_UP,
    STATUS_BLOCKED,
    Analysis,
)

ASPECT_CLEAR = "Limpa"
ASPECT_CLOUDY = "Turva"
ASPECT_GREEN = "Verde (algas)"
ASPECT_METALS = "Verde transparente (metais)"
ASPECT_STAINS = "Manchas coloridas (metais)"
ASPECTS = (ASPECT_CLEAR, ASPECT_CLOUDY, ASPECT_GREEN, ASPECT_METALS, ASPECT_STAINS)
METAL_ASPECTS = (ASPECT_METALS, ASPECT_STAINS)
# Valores salvos por versões anteriores
LEGACY_ASPECTS = {"Verde": ASPECT_GREEN}

KEY_ALGAECIDE = "algicida"
KEY_CLARIFIER = "clarificante"
KEY_CHLORINE = "cloro"
KEY_METALS = "removedor_metais"

ALGAECIDE_MAINTENANCE_ML_PER_M3 = 5.0
ALGAECIDE_SHOCK_ML_PER_M3 = 7.0
ALGAECIDE_SHOCK_INTERVAL_DAYS = 7
CLARIFIER_PREVENTIVE_ML_PER_M3 = 1.5
CLARIFIER_CORRECTIVE_ML_PER_M3 = 4.5
CLARIFIER_CORRECTIVE_INTERVAL_DAYS = 1
CHLORINE_ALGAECIDE_GAP_HOURS = 12

METALS_ML_PER_M3_PER_PPM = 15.0
METALS_REMOVAL_ML_PER_M3 = 50.0
METALS_REPEAT_DAYS = 7
METALS_WINDOW_DAYS = 7  # cloro limitado e sem choque por 7 dias após a aplicação
METALS_MAX_CHLORINE = 1.0

ALGAECIDE_PH_MIN = 7.4
ALGAECIDE_PH_MAX = 7.6

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


def _ph_block_message(ph: float, what: str) -> str:
    message = f"Ajuste o pH para 7,4 a 7,6 antes de {what}"
    if ph > ALGAECIDE_PH_MAX:
        message += " (o rótulo do pH Menos só traz dose a partir de pH 7,8)"
    return message


def _round_ml(value: float) -> float:
    return float(round(value / 5.0) * 5) if value >= 50 else float(round(value))


def metals_window_end(last_applied: datetime | None, now: datetime) -> datetime | None:
    """Fim da janela de 7 dias (cloro até 1 ppm, sem choque) após o removedor de metais."""
    if last_applied is None:
        return None
    end = last_applied + timedelta(days=METALS_WINDOW_DAYS)
    return end if now < end else None


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
) -> MaintenanceItem:
    green = aspect == ASPECT_GREEN
    name = "Algicida de choque" if green else "Algicida de manutenção"
    mode = "choque" if green else "manutenção"
    per_m3 = ALGAECIDE_SHOCK_ML_PER_M3 if green else ALGAECIDE_MAINTENANCE_ML_PER_M3
    interval = float(ALGAECIDE_SHOCK_INTERVAL_DAYS if green else interval_days)
    amount = _round_ml(per_m3 * volume_m3)

    notes = [
        "Nunca aplique junto com cloro: deixe pelo menos 12 h entre os dois.",
        "Mantenha o cloro livre entre 2 e 4 ppm.",
    ]
    if chlorine_limited:
        notes[1] = (
            "Conflito entre rótulos: o algicida pede cloro de 2 a 4 ppm, mas o removedor de metais "
            "exige no máximo 1 ppm até 7 dias depois da aplicação. Não eleve o cloro agora."
        )
    if green:
        notes.append("Mantenha a filtração por 30 a 60 min para homogeneizar a solução.")
        notes.append("Quando as algas morrerem (ficam marrons), escove e aspire. Repita se restarem sinais.")
        notes.append("O algicida de choque é à base de íons de cobre: não use se a cor verde for de metais.")
    else:
        notes.append("Aspire o fundo pelo menos 2 vezes por semana.")

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
        gap_end = last_chlorine + timedelta(hours=CHLORINE_ALGAECIDE_GAP_HOURS)
        if now < gap_end:
            wait_until = gap_end

    if ph is not None and not ALGAECIDE_PH_MIN <= ph <= ALGAECIDE_PH_MAX:
        item.status = ITEM_BLOCKED
        item.blocked_by = "ph"
        item.message = _ph_block_message(ph, f"aplicar o {name.lower()}")
    elif wait_until is not None:
        item.status = ITEM_WAIT
        item.wait_until = wait_until
        item.message = (
            f"Aguardar até {fmt_dt(wait_until, now)} (12 h após o cloro) "
            f"para aplicar {int(amount)} mL de {name.lower()}"
        )
    else:
        item.status = ITEM_DUE
        item.message = f"Adicionar {int(amount)} mL de {name.lower()}"
        if chlorine is not None and not 2.0 <= chlorine <= 4.0 and not chlorine_limited:
            item.notes.insert(0, "O cloro livre está fora de 2 a 4 ppm; corrija-o (em outro horário).")
    return item


def evaluate_clarifier(
    volume_m3: float,
    aspect: str,
    last_applied: datetime | None,
    now: datetime,
    interval_days: float,
) -> MaintenanceItem:
    corrective = aspect in (ASPECT_CLOUDY, ASPECT_GREEN)
    name = "Clarificante corretivo" if corrective else "Clarificante preventivo"
    mode = "corretivo" if corrective else "preventivo"
    per_m3 = CLARIFIER_CORRECTIVE_ML_PER_M3 if corrective else CLARIFIER_PREVENTIVE_ML_PER_M3
    interval = float(CLARIFIER_CORRECTIVE_INTERVAL_DAYS if corrective else interval_days)
    amount = _round_ml(per_m3 * volume_m3)
    filtering = "6 a 8 h" if corrective else "1 a 2 h"

    notes = [
        "Faça a retrolavagem do filtro se necessário e ligue a filtração.",
        "Dilua a dose em um balde com água e espalhe a solução pela superfície da piscina.",
        f"Mantenha a filtração por {filtering} e depois aspire a sujeira decantada.",
        "Não substitui cloro nem controle do pH.",
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
) -> MaintenanceItem:
    """Removedor de metais (Genquest): só entra em ação com aspecto de metais."""
    name = "Removedor de metais"
    window_end = metals_window_end(last_applied, now)
    repeat_at = last_applied + timedelta(days=METALS_REPEAT_DAYS) if last_applied else None
    item = MaintenanceItem(
        KEY_METALS, name, "inativo", ITEM_OK, "", 0.0, float(METALS_REPEAT_DAYS), last_applied, repeat_at
    )

    if aspect not in METAL_ASPECTS:
        if window_end is not None:
            item.mode = "em ação"
            item.message = (
                f"{name} em ação até {fmt_dt(window_end, now)}: "
                "cloro no máximo 1 ppm e sem choque"
            )
        else:
            item.message = "Não necessário (sem sinais de metais na água)"
        return item

    stains = aspect == ASPECT_STAINS
    ppm = float(metals_ppm) if metals_ppm else 0.0
    per_m3 = METALS_ML_PER_M3_PER_PPM * ppm if ppm > 0 else METALS_REMOVAL_ML_PER_M3
    amount = _round_ml(per_m3 * volume_m3)
    item.mode = "tratamento"

    notes: list[str] = []
    if aspect == ASPECT_METALS:
        notes.append("Água verde e transparente sugere metais pela aparência. Só o resultado confirma: reavalie a cor após 7 dias.")
        notes.append("Fontes possíveis de metais: água de poço (o Genquest é indicado para piscinas abastecidas assim) e o algicida de choque, que contém íons de cobre.")
    if ppm > 0:
        notes.append(f"Dose do rótulo: 15 mL/m³ por ppm de metal ({ppm:g} ppm informados).")
    else:
        notes.append("Dose de eliminação do rótulo: 50 mL/m³.")
    bottles = amount / 1000.0
    notes.append(f"O frasco do Genquest tem 1 L: esta dose equivale a {bottles:.1f} frasco(s).".replace(".", ","))
    notes += [
        "Aplique de preferência à noite ou ao fim da tarde, sobre o bocal de retorno, com a filtração ligada.",
        "Mantenha o cloro livre em no máximo 1 ppm e não faça oxidação de choque por 7 dias.",
        "Funcione a filtração diariamente"
        + (" e retrolave o filtro todo dia enquanto durar o tratamento." if stains else "."),
    ]
    if stains:
        notes.append("Escove as manchas com frequência por 5 a 7 dias.")
    notes.append("Turbidez depois da aplicação é temporária. Aguarde 1 h para usar a piscina.")
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
    elif ph is not None and not ALGAECIDE_PH_MIN <= ph <= ALGAECIDE_PH_MAX:
        item.status = ITEM_BLOCKED
        item.blocked_by = "ph"
        item.message = _ph_block_message(ph, f"o {name.lower()}")
    elif chlorine is not None and chlorine > METALS_MAX_CHLORINE:
        item.status = ITEM_BLOCKED
        item.blocked_by = "chlorine"
        item.message = (
            f"Aguarde o cloro baixar a no máximo 1 ppm antes do {name.lower()} "
            "(não adicione cloro)"
        )
    else:
        item.status = ITEM_DUE
        item.message = f"Adicionar {int(amount)} mL de {name.lower()}"
        if chlorine is None:
            item.notes.insert(0, "Confirme que o cloro livre está em no máximo 1 ppm antes de aplicar.")
    return item


# ---------------------------------------------------------------------------
# Instruções de aplicação
# ---------------------------------------------------------------------------
PPE = "Use máscara, luvas e óculos de proteção."
SPREAD_BUCKET = (
    "Adicione direto da embalagem ou dissolva num balde plástico com água da piscina "
    "e distribua uniformemente sobre a superfície."
)
FILTER_30_60 = "Mantenha a filtração ligada por 30 a 60 min para homogeneizar."

INSTRUCTIONS: dict[str, list[str]] = {
    PRODUCT_ALK_UP: [
        PPE,
        SPREAD_BUCKET,
        FILTER_30_60,
        "No dia seguinte, analise o pH e corrija: pH Mais se estiver abaixo de 7,2, pH Menos se acima de 7,8.",
    ],
    PRODUCT_PH_UP: [
        PPE,
        SPREAD_BUCKET,
        FILTER_30_60,
        "Teste o pH 1 h depois da aplicação para confirmar.",
    ],
    PRODUCT_PH_DOWN: [
        PPE,
        "Dilua a dose em um balde plástico com água da piscina (sempre o produto na água, nunca o inverso).",
        "Espalhe sobre a superfície com a válvula em Filtrar e mantenha a filtração por 30 a 60 min.",
        "No dia seguinte, reanalise o pH e a alcalinidade; se ainda estiverem fora da faixa, repita.",
    ],
    PRODUCT_CHLORINE: [
        PPE,
        "Espalhe direto sobre a água. Em piscinas de fibra, vinil ou pintadas, dissolva a dose antes em um recipiente plástico com água da piscina e use só a solução sobrenadante; não use grânulos que não dissolveram.",
        "Não aplique no mesmo horário de algicida: deixe 12 h entre eles.",
        "Analise o cloro livre antes da próxima aplicação (faixa de 2 a 4 ppm) e só use a piscina com o residual abaixo de 10 ppm.",
    ],
}


def build_instructions(
    analysis: Analysis,
    algaecide: MaintenanceItem,
    clarifier: MaintenanceItem,
    metals: MaintenanceItem,
    now: datetime,
) -> tuple[str, int]:
    """Monta o texto em Markdown com a ordem e o modo de aplicação.

    Retorna (markdown, quantidade de aplicações pendentes).
    """
    steps: list[tuple[str, str, list[str]]] = []  # (título, linha da ordem, instruções)
    warnings: list[str] = []
    for rec in analysis.recommendations:
        if rec.actionable and rec.product and rec.amount > 0:
            qty = f"{int(round(rec.amount))} {rec.unit}"
            line = f"{rec.product}: {qty}"
            if rec.applications > 1:
                line += f" em {rec.applications} aplicações de {int(round(rec.per_application))} {rec.unit}, uma por dia"
            steps.append((rec.product, line, list(INSTRUCTIONS.get(rec.product, []))))
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
    lines.append(
        "Liberação da piscina: 30 min após pH Mais, pH Menos, algicida e clarificante; "
        "1 h após o removedor de metais; com cloro, só com o residual abaixo de 10 ppm."
    )
    return "\n".join(lines), len(steps)
