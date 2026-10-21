"""Botões do tratamento por etapas: registrar a etapa e pular a etapa."""
from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .entity import PoolEntity
from .pool import PoolManager


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    manager: PoolManager = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([RegisterStepButton(manager), SkipStepButton(manager)])


class RegisterStepButton(PoolEntity, ButtonEntity):
    """Registra o produto e a quantidade informados como aplicados."""

    _attr_icon = "mdi:check-circle-outline"

    def __init__(self, manager: PoolManager) -> None:
        super().__init__(manager, "register_step", "Registrar etapa")

    async def async_press(self) -> None:
        self.manager.register_step()


class SkipStepButton(PoolEntity, ButtonEntity):
    """Pula a etapa sugerida sem aplicar nada."""

    _attr_icon = "mdi:skip-next-circle-outline"

    def __init__(self, manager: PoolManager) -> None:
        super().__init__(manager, "skip_step", "Pular etapa")

    async def async_press(self) -> None:
        self.manager.skip_step()
