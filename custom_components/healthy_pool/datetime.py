"""Data e hora da última medição."""
from __future__ import annotations

from datetime import datetime

from homeassistant.components.datetime import DateTimeEntity
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
    async_add_entities([PoolMeasurementDate(manager)])


class PoolMeasurementDate(PoolEntity, DateTimeEntity):
    """Data da medição (atualizada automaticamente ao informar uma medição)."""

    _attr_icon = "mdi:calendar-clock"

    def __init__(self, manager: PoolManager) -> None:
        super().__init__(manager, "measured_at", "Data da medição")

    @property
    def native_value(self) -> datetime | None:
        return self.manager.measured_at

    async def async_set_value(self, value: datetime) -> None:
        self.manager.set_measured_at(value)
