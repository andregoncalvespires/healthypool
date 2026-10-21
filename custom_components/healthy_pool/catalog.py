"""Catálogo de produtos: fichas em JSON com dose, esperas, regras e instruções (sem dependências do HA).

Cada ficha é um arquivo ``.json`` em ``products/`` (embutidas) ou na pasta de produtos do usuário
(``<config>/healthy_pool_products``). Cada produto cumpre uma **função** (``role``); a integração
usa, para cada função, o produto escolhido nas opções. Veja ``products/README.md``.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable

_LOGGER = logging.getLogger(__name__)

BUILTIN_DIR = Path(__file__).parent / "products"
DEFAULT_BRAND_PREFIX = "genco_"

ROLE_ALK_UP = "alk_up"
ROLE_ACID = "acid"
ROLE_PH_UP = "ph_up"
ROLE_CHLORINE = "chlorine"
ROLE_ALGAECIDE = "algaecide"
ROLE_CLARIFIER = "clarifier"
ROLE_METALS = "metals_remover"

# função -> (descrição, unidade, campos obrigatórios em "dosing")
ROLES: dict[str, tuple[str, str, tuple[str, ...]]] = {
    ROLE_ALK_UP: ("Subir alcalinidade", "g", ("g_per_m3_per_ppm",)),
    ROLE_ACID: (
        "Baixar alcalinidade e pH",
        "mL",
        ("alkalinity_ml_per_m3_per_ppm", "ph_steps", "max_ml_per_m3_per_application"),
    ),
    ROLE_PH_UP: ("Subir pH", "g", ("table_target_ph", "table_alkalinity", "table")),
    ROLE_CHLORINE: ("Cloro", "g", ("available_chlorine",)),
    ROLE_ALGAECIDE: ("Algicida", "mL", ("maintenance_ml_per_m3", "shock_ml_per_m3")),
    ROLE_CLARIFIER: ("Clarificante", "mL", ("preventive_ml_per_m3", "corrective_ml_per_m3")),
    ROLE_METALS: ("Removedor de metais", "mL", ("ml_per_m3_per_ppm", "removal_ml_per_m3")),
}
ROLE_ORDER = tuple(ROLES)
DEFAULT_IDS = {
    ROLE_ALK_UP: "genco_ph_certo",
    ROLE_ACID: "genco_ph_menos",
    ROLE_PH_UP: "genco_ph_mais",
    ROLE_CHLORINE: "genco_genclor",
    ROLE_ALGAECIDE: "genco_algicida",
    ROLE_CLARIFIER: "genco_genfloc",
    ROLE_METALS: "genco_genquest",
}
CONF_PRODUCT_PREFIX = "product_"


@dataclass(frozen=True)
class Product:
    """Ficha de um produto."""

    id: str
    brand: str
    name: str
    role: str
    unit: str
    remeasure_hours: float = 0.0
    dosing: dict[str, Any] = field(default_factory=dict)
    rules: dict[str, Any] = field(default_factory=dict)
    instructions: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()
    source: str = ""
    message_name: str | None = None
    short_name: str | None = None

    @property
    def label(self) -> str:
        return f"{self.brand} {self.name}".strip()

    @property
    def text_name(self) -> str:
        """Nome usado dentro de frases ("Adicionar 100 g de ...")."""
        return self.message_name or self.name

    @property
    def item_name(self) -> str:
        return self.short_name or self.name


def parse_product(data: dict[str, Any], source_file: str = "") -> Product:
    """Valida e cria um produto; levanta ValueError se a ficha estiver incompleta."""
    for key in ("id", "brand", "name", "role", "unit", "dosing"):
        if key not in data:
            raise ValueError(f"campo obrigatório ausente: {key}")
    role = data["role"]
    if role not in ROLES:
        raise ValueError(f"função desconhecida: {role}")
    unit = data["unit"]
    if unit not in ("g", "mL"):
        raise ValueError("unit deve ser 'g' ou 'mL'")
    dosing = data["dosing"]
    missing = [k for k in ROLES[role][2] if k not in dosing]
    if missing:
        raise ValueError(f"dosing sem: {', '.join(missing)}")
    return Product(
        id=str(data["id"]),
        brand=str(data["brand"]),
        name=str(data["name"]),
        role=role,
        unit=unit,
        remeasure_hours=float(data.get("remeasure_hours", 0)),
        dosing=dict(dosing),
        rules=dict(data.get("rules") or {}),
        instructions=tuple(data.get("instructions") or ()),
        notes=tuple(data.get("notes") or ()),
        source=str(data.get("source", "")),
        message_name=data.get("message_name"),
        short_name=data.get("short_name"),
    )


def load_products(directories: Iterable[Path | str]) -> dict[str, Product]:
    """Lê as fichas das pastas (as últimas sobrescrevem ids repetidos). Fichas inválidas são ignoradas."""
    catalog: dict[str, Product] = {}
    for directory in directories:
        path = Path(directory)
        if not path.is_dir():
            continue
        for file in sorted(path.glob("*.json")):
            try:
                product = parse_product(json.loads(file.read_text(encoding="utf-8")), file.name)
            except (OSError, ValueError, TypeError) as err:
                _LOGGER.warning("Ficha de produto ignorada (%s): %s", file.name, err)
                continue
            catalog[product.id] = product
    return catalog


@lru_cache(maxsize=1)
def builtin_catalog() -> dict[str, Product]:
    return load_products([BUILTIN_DIR])


def products_for_role(catalog: dict[str, Product], role: str) -> list[Product]:
    return sorted((p for p in catalog.values() if p.role == role), key=lambda p: (p.brand, p.name))


class ProductSet:
    """Um produto escolhido para cada função."""

    def __init__(self, products: dict[str, Product]) -> None:
        missing = [r for r in ROLES if r not in products]
        if missing:
            raise ValueError(f"faltam produtos para: {', '.join(missing)}")
        self._products = dict(products)

    def __getitem__(self, role: str) -> Product:
        return self._products[role]

    def get(self, role: str) -> Product | None:
        return self._products.get(role)

    def roles(self) -> tuple[str, ...]:
        return ROLE_ORDER

    @property
    def alk_up(self) -> Product:
        return self._products[ROLE_ALK_UP]

    @property
    def acid(self) -> Product:
        return self._products[ROLE_ACID]

    @property
    def ph_up(self) -> Product:
        return self._products[ROLE_PH_UP]

    @property
    def chlorine(self) -> Product:
        return self._products[ROLE_CHLORINE]

    @property
    def algaecide(self) -> Product:
        return self._products[ROLE_ALGAECIDE]

    @property
    def clarifier(self) -> Product:
        return self._products[ROLE_CLARIFIER]

    @property
    def metals(self) -> Product:
        return self._products[ROLE_METALS]

    def names(self) -> dict[str, str]:
        """Nomes por função, para trocar {alk_up}, {acid}... nos textos das fichas."""
        return {role: p.name for role, p in self._products.items()}

    @classmethod
    def from_choices(
        cls, catalog: dict[str, Product], choices: dict[str, str | None]
    ) -> "ProductSet":
        """Monta o conjunto pelas escolhas (id por função); usa o padrão se a escolha sumiu."""
        builtin = builtin_catalog()
        chosen: dict[str, Product] = {}
        for role in ROLES:
            product = catalog.get(choices.get(role) or "")
            if product is None or product.role != role:
                product = catalog.get(DEFAULT_IDS[role]) or builtin[DEFAULT_IDS[role]]
            chosen[role] = product
        return cls(chosen)


def default_products() -> ProductSet:
    """Conjunto padrão (Genco), sem ler a pasta do usuário."""
    return ProductSet.from_choices(builtin_catalog(), {})


def render(text: str, products: ProductSet) -> str:
    """Troca {alk_up}, {acid}, {ph_up}... pelos nomes dos produtos escolhidos."""
    try:
        return text.format_map(products.names())
    except (KeyError, IndexError, ValueError):
        return text
