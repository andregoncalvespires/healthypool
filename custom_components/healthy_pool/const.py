"""Constantes da integração Healthy Pool."""
from __future__ import annotations

DOMAIN = "healthy_pool"
DEFAULT_NAME = "Piscina"

STORAGE_VERSION = 1

# Pasta (dentro da configuração do HA) para fichas de produtos próprias; veja products/README.md
USER_PRODUCTS_DIRNAME = "healthy_pool_products"

# --- Geometria (todas as medidas em cm) ---
CONF_NAME = "name"
CONF_LENGTH = "length_cm"
CONF_WIDTH = "width_cm"
CONF_SHALLOW_LENGTH = "shallow_length_cm"
CONF_SHALLOW_DEPTH = "shallow_depth_cm"
CONF_DEEP_DEPTH = "deep_depth_cm"
CONF_STAIR_STEPS = "stair_steps"
CONF_STAIR_TREAD = "stair_tread_cm"
CONF_STAIR_WIDTH = "stair_width_cm"
CONF_FREEBOARD = "freeboard_cm"
CONF_SHAPE = "shape"
CONF_MANUAL_VOLUME = "manual_volume_m3"

SHAPE_RECT = "retangular"  # retângulo com área rasa e escada opcionais
SHAPE_SLOPED = "inclinada"  # retângulo com fundo em declive
SHAPE_ROUND = "redonda"
SHAPE_OVAL = "oval"
SHAPE_MANUAL = "manual"  # volume informado direto
SHAPES = (SHAPE_RECT, SHAPE_SLOPED, SHAPE_ROUND, SHAPE_OVAL, SHAPE_MANUAL)
CONF_TEMP_ENTITY = "temperature_entity"

# --- Faixas e metas ---
CONF_ALK_MIN = "alk_min"
CONF_ALK_TARGET = "alk_target"
CONF_ALK_MAX = "alk_max"
CONF_PH_MIN = "ph_min"
CONF_PH_TARGET = "ph_target"
CONF_PH_MAX = "ph_max"
CONF_CL_MIN = "cl_min"
CONF_CL_TARGET = "cl_target"
CONF_CL_MAX = "cl_max"
CONF_PH_UP_FACTOR = "ph_up_factor"
CONF_ALGAECIDE_DAYS = "algaecide_interval_days"
CONF_CLARIFIER_DAYS = "clarifier_interval_days"

GEOMETRY_KEYS = (
    CONF_LENGTH,
    CONF_WIDTH,
    CONF_SHALLOW_LENGTH,
    CONF_SHALLOW_DEPTH,
    CONF_DEEP_DEPTH,
    CONF_STAIR_STEPS,
    CONF_STAIR_TREAD,
    CONF_STAIR_WIDTH,
    CONF_FREEBOARD,
)

from .catalog import CONF_PRODUCT_PREFIX, DEFAULT_IDS  # noqa: E402

DEFAULTS: dict[str, float | int | str] = {
    CONF_SHAPE: SHAPE_RECT,
    CONF_MANUAL_VOLUME: 0,
    **{f"{CONF_PRODUCT_PREFIX}{role}": pid for role, pid in DEFAULT_IDS.items()},
    # Piscina do André: 395 x 700 cm, área rasa de 200 cm, escada de 3 degraus de 37 cm
    CONF_LENGTH: 700,
    CONF_WIDTH: 395,
    CONF_SHALLOW_LENGTH: 200,
    CONF_SHALLOW_DEPTH: 45,  # profundidade do piso da área rasa, medida da borda
    CONF_DEEP_DEPTH: 155,  # profundidade total da parte funda, medida da borda
    CONF_STAIR_STEPS: 3,
    CONF_STAIR_TREAD: 37,
    CONF_STAIR_WIDTH: 90,  # estimativa a partir do desenho; confirme na piscina
    CONF_FREEBOARD: 6.5,  # altura livre entre a água e a borda (5 a 8 cm)
    CONF_ALK_MIN: 80,
    CONF_ALK_TARGET: 100,
    CONF_ALK_MAX: 120,
    CONF_PH_MIN: 7.2,
    CONF_PH_TARGET: 7.5,
    CONF_PH_MAX: 7.8,
    CONF_CL_MIN: 2.0,
    CONF_CL_TARGET: 3.0,
    CONF_CL_MAX: 4.0,
    CONF_PH_UP_FACTOR: 1.0,
    CONF_ALGAECIDE_DAYS: 7,  # algicida de manutenção: semanal (rótulo)
    CONF_CLARIFIER_DAYS: 7,  # clarificante preventivo: semanal (rótulo)
}

SERVICE_RECORD_MEASUREMENT = "registrar_medicao"
SERVICE_RECORD_STEP = "registrar_etapa"
