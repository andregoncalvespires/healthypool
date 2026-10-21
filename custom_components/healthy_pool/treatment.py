"""Tratamento por etapas: eficácia e histórico (sem dependências do HA)."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from .catalog import (
    ROLE_ACID,
    ROLE_ALK_UP,
    ROLE_CHLORINE,
    ROLE_PH_UP,
    ProductSet,
    default_products,
)
from typing import Any

PARAM_ALK = "alkalinity"
PARAM_PH = "ph"
PARAM_CL = "chlorine"
PARAM_ASPECT = "aspecto"
PARAMS = (PARAM_ALK, PARAM_PH, PARAM_CL)

PARAM_LABELS = {PARAM_ALK: "Alcalinidade", PARAM_PH: "pH", PARAM_CL: "Cloro livre", PARAM_ASPECT: "Aspecto da água"}
PARAM_UNITS = {PARAM_ALK: "ppm", PARAM_PH: "", PARAM_CL: "ppm"}

HISTORY_LIMIT = 20

# Faixa em que a variação medida conta como "dentro do esperado" (medido ÷ esperado).
EXPECTED_LOW = 0.7
EXPECTED_HIGH = 1.3

VERDICT_OK = "dentro do esperado"
VERDICT_LOW = "abaixo do esperado"
VERDICT_HIGH = "acima do esperado"

# Chaves antigas (antes do catálogo) -> função do produto
LEGACY_KEYS = {
    "ph_certo": "alk_up",
    "ph_mais": "ph_up",
    "ph_menos": "acid",
    "cloro": "chlorine",
    "algicida": "algaecide",
    "clarificante": "clarifier",
    "removedor_metais": "metals_remover",
}

# parâmetro que a função corrige (None: depende do caso ou não se aplica)
ROLE_PARAMS: dict[str, str | None] = {
    ROLE_ALK_UP: PARAM_ALK,
    ROLE_PH_UP: PARAM_PH,
    ROLE_CHLORINE: PARAM_CL,
    ROLE_ACID: None,
    "algaecide": None,
    "clarifier": None,
    "metals_remover": None,
}


def infer_param(role: str, suggested_param: str | None, alk: float | None, alk_max: float) -> str | None:
    """Parâmetro que uma aplicação vai corrigir (o ácido serve para alcalinidade e para pH)."""
    param = ROLE_PARAMS.get(role)
    if param:
        return param
    if role == ROLE_ACID:
        if suggested_param in (PARAM_ALK, PARAM_PH):
            return suggested_param
        return PARAM_ALK if alk is not None and alk > alk_max else PARAM_PH
    return None


def expected_change(
    step: dict[str, Any],
    param: str,
    volume_m3: float,
    before: float | None,
    target: float,
    products: ProductSet | None = None,
) -> float | None:
    """Variação esperada do parâmetro com a quantidade realmente aplicada, pelos rótulos."""
    amount = float(step.get("amount") or 0)
    if amount <= 0 or volume_m3 <= 0:
        return None
    P = products or default_products()
    key = step["key"]
    if key == ROLE_ALK_UP:
        return amount / volume_m3 / float(P.alk_up.dosing["g_per_m3_per_ppm"])
    if key == ROLE_ACID and param == PARAM_ALK:
        return -amount / volume_m3 / float(P.acid.dosing["alkalinity_ml_per_m3_per_ppm"])
    if key == ROLE_CHLORINE:
        return amount * float(P.chlorine.dosing["available_chlorine"]) / volume_m3
    # pH: a dose sugerida levaria até a meta; proporcional ao que foi aplicado
    planned = step.get("planned_amount")
    if param == PARAM_PH and planned and before is not None:
        return (target - before) * amount / float(planned)
    return None


def evaluate_cycle(
    cycle: dict[str, Any],
    volume_m3: float,
    targets: dict[str, float],
    products: ProductSet | None = None,
) -> list[dict[str, Any]]:
    """Compara antes e depois de cada parâmetro tratado no ciclo."""
    results: list[dict[str, Any]] = []
    after = cycle.get("after") or {}
    before = cycle.get("before") or {}
    steps = [s for s in cycle.get("steps", []) if not s.get("skipped")]

    for param in PARAMS:
        mine = [s for s in steps if s.get("param") == param]
        if not mine or after.get(param) is None:
            continue
        b, a = before.get(param), after[param]
        expected: float | None = 0.0
        for s in mine:
            delta = expected_change(s, param, volume_m3, b, targets.get(param, 0.0), products)
            expected = None if (delta is None or expected is None) else expected + delta
        item: dict[str, Any] = {
            "parametro": PARAM_LABELS[param],
            "produtos": [f"{s['name']} {_fmt(s['amount'])} {s['unit']}" for s in mine],
            "antes": b,
            "depois": a,
            "unidade": PARAM_UNITS[param],
        }
        if b is not None:
            item["medido"] = round(a - b, 2)
        if expected is not None and abs(expected) > 1e-6 and b is not None:
            ratio = (a - b) / expected
            item["esperado"] = round(expected, 2)
            item["eficacia_pct"] = round(ratio * 100)
            item["veredito"] = (
                VERDICT_LOW if ratio < EXPECTED_LOW else VERDICT_HIGH if ratio > EXPECTED_HIGH else VERDICT_OK
            )
        notes: list[str] = []
        if param == PARAM_CL:
            notes.append("O cloro é consumido pelo uso e pelo sol; valor menor que o esperado é comum.")
        early = _measured_early(mine, cycle.get("after_at", {}).get(param))
        if early:
            notes.append("Medido antes do prazo do rótulo; a medição final pode ser diferente.")
        if notes:
            item["observacao"] = " ".join(notes)
        results.append(item)

    aspect_steps = [s for s in steps if s.get("param") is None]
    if aspect_steps and after.get(PARAM_ASPECT) is not None:
        results.append(
            {
                "parametro": PARAM_LABELS[PARAM_ASPECT],
                "produtos": [f"{s['name']} {_fmt(s['amount'])} {s['unit']}" for s in aspect_steps],
                "antes": before.get(PARAM_ASPECT),
                "depois": after[PARAM_ASPECT],
            }
        )
    return results


def _measured_early(steps: list[dict[str, Any]], after_at: str | None) -> bool:
    if not after_at:
        return False
    measured = datetime.fromisoformat(after_at)
    return any(
        measured < datetime.fromisoformat(s["at"]) + timedelta(hours=float(s.get("wait_hours") or 0))
        for s in steps
    )


def _fmt(value: float) -> str:
    return str(int(round(value))) if abs(value - round(value)) < 0.05 else f"{value:.1f}"


def summarize_results(results: list[dict[str, Any]]) -> str:
    """Texto curto com o resultado de cada parâmetro."""
    if not results:
        return "Sem resultado ainda: faça uma nova medição depois de aplicar."
    parts = []
    for r in results:
        if r["parametro"] == PARAM_LABELS[PARAM_ASPECT]:
            parts.append(f"Aspecto: {r['antes']} → {r['depois']}")
            continue
        unit = f" {r['unidade']}" if r.get("unidade") else ""
        line = f"{r['parametro']}: {r['antes']} → {r['depois']}{unit}"
        if "eficacia_pct" in r:
            line += f" (esperado {r['esperado']:+g}, medido {r['medido']:+g}; {r['eficacia_pct']} %, {r['veredito']})"
        parts.append(line)
    return "; ".join(parts)
