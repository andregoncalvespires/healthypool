"""Aspecto da água (limpa, turva ou verde)."""
from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .entity import PoolEntity
from .maintenance import ASPECTS
from .pool import PoolManager


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    manager: PoolManager = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([PoolAspectSelect(manager), PoolAppliedProductSelect(manager)])


class PoolAspectSelect(PoolEntity, SelectEntity):
    """Define se a água precisa de dose de manutenção ou corretiva."""

    _attr_options = list(ASPECTS)
    _attr_icon = "mdi:water-opacity"

    def __init__(self, manager: PoolManager) -> None:
        super().__init__(manager, "aspect", "Aspecto da água")

    @property
    def current_option(self) -> str:
        return self.manager.aspect

    async def async_select_option(self, option: str) -> None:
        self.manager.set_aspect(option)


class PoolAppliedProductSelect(PoolEntity, SelectEntity):
    """Produto que está sendo registrado (já vem com o da etapa sugerida)."""

    _attr_icon = "mdi:flask-outline"

    def __init__(self, manager: PoolManager) -> None:
        super().__init__(manager, "applied_product", "Produto aplicado")

    @property
    def options(self) -> list[str]:
        P = self.manager.products
        return [P[role].name for role in P.roles()]

    @property
    def current_option(self) -> str | None:
        key = self.manager.effective_product
        return self.manager.products[key].name if key else None

    async def async_select_option(self, option: str) -> None:
        P = self.manager.products
        key = next((role for role in P.roles() if P[role].name == option), None)
        self.manager.select_product(key)
