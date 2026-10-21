"""Cálculo do volume de água a partir da geometria da piscina (sem dependências do HA).

Modelo (medidas em cm, resultado em m³):

* A piscina é um retângulo ``length x width``.
* Os primeiros ``shallow_length`` cm formam a área rasa (prainha), com piso a
  ``shallow_depth`` cm da borda.
* O restante é a parte funda, com piso a ``deep_depth`` cm da borda.
* A escada fica no fim da área rasa, descendo em direção à parte funda: ocupa
  ``stair_steps x stair_tread`` cm de comprimento e ``stair_width`` cm de largura.
  Entre o piso raso e o fundo há ``stair_steps + 1`` degraus de altura iguais.
* A lâmina de água fica ``freeboard`` cm abaixo da borda.

Outros formatos (``shape``):

* ``retangular``: o modelo acima (área rasa e escada podem ser zeradas para uma piscina simples).
* ``inclinada``: retângulo ``length x width`` com fundo em declive, de ``shallow_depth`` (início)
  a ``deep_depth`` (fim).
* ``redonda``: círculo de diâmetro ``length``, profundidade média ``deep_depth``.
* ``oval``: elipse ``length x width``, profundidade média ``deep_depth``.
* ``manual``: usa ``manual_volume_m3`` direto (a altura livre não altera o volume).
"""
from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class PoolGeometry:
    """Dimensões da piscina em centímetros."""

    length_cm: float
    width_cm: float
    shallow_length_cm: float
    shallow_depth_cm: float
    deep_depth_cm: float
    stair_steps: int = 0
    stair_tread_cm: float = 0.0
    stair_width_cm: float = 0.0
    shape: str = "retangular"
    manual_volume_m3: float = 0.0


def _single(total_m3: float) -> dict[str, float]:
    total = round(total_m3, 3)
    return {"parte_funda_m3": total, "area_rasa_m3": 0.0, "escada_m3": 0.0, "total_m3": total}


def volume_breakdown(geometry: PoolGeometry, freeboard_cm: float) -> dict[str, float]:
    """Retorna o volume de água (m³) por região e o total."""
    g = geometry
    fb = max(float(freeboard_cm), 0.0)

    if g.shape == "manual":
        return _single(max(g.manual_volume_m3, 0.0))
    if g.shape in ("redonda", "oval"):
        area = math.pi * (g.length_cm / 2) ** 2 if g.shape == "redonda" else math.pi / 4 * g.length_cm * g.width_cm
        return _single(area * max(g.deep_depth_cm - fb, 0.0) * 1e-6)
    if g.shape == "inclinada":
        slices = 200
        depth = 0.0
        for i in range(slices):
            d = g.shallow_depth_cm + (g.deep_depth_cm - g.shallow_depth_cm) * (i + 0.5) / slices
            depth += max(d - fb, 0.0) / slices
        return _single(g.length_cm * g.width_cm * depth * 1e-6)

    deep_water = max(g.deep_depth_cm - fb, 0.0)
    shallow_water = max(g.shallow_depth_cm - fb, 0.0)

    steps = max(int(g.stair_steps), 0)
    run = min(steps * g.stair_tread_cm, g.shallow_length_cm) if steps else 0.0
    stair_w = min(g.stair_width_cm, g.width_cm) if run > 0 else 0.0
    tread = run / steps if steps else 0.0

    deep_area = g.width_cm * max(g.length_cm - g.shallow_length_cm, 0.0)
    shallow_area = g.width_cm * g.shallow_length_cm - stair_w * run

    deep_cm3 = deep_area * deep_water
    shallow_cm3 = max(shallow_area, 0.0) * shallow_water

    stairs_cm3 = 0.0
    if steps:
        riser = max(g.deep_depth_cm - g.shallow_depth_cm, 0.0) / (steps + 1)
        for i in range(1, steps + 1):
            depth_below_edge = g.shallow_depth_cm + i * riser
            stairs_cm3 += stair_w * tread * max(depth_below_edge - fb, 0.0)

    to_m3 = 1e-6
    deep = deep_cm3 * to_m3
    shallow = shallow_cm3 * to_m3
    stairs = stairs_cm3 * to_m3
    return {
        "parte_funda_m3": round(deep, 3),
        "area_rasa_m3": round(shallow, 3),
        "escada_m3": round(stairs, 3),
        "total_m3": round(deep + shallow + stairs, 3),
    }


def water_volume_m3(geometry: PoolGeometry, freeboard_cm: float) -> float:
    """Volume total de água em m³."""
    return volume_breakdown(geometry, freeboard_cm)["total_m3"]
