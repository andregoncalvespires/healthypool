"""Indicadores de pendência: tratamento, algicida e clarificante."""
from __future__ import annotations

from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
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
    async_add_entities(
        [
            NeedsTreatmentSensor(manager),
            MaintenancePendingSensor(manager, "algaecide_due", "Aplicar algicida", "algaecide", "mdi:bacteria-outline"),
            MaintenancePendingSensor(manager, "clarifier_due", "Aplicar clarificante", "clarifier", "mdi:water-opacity"),
            MaintenancePendingSensor(manager, "metals_due", "Aplicar removedor de metais", "metals", "mdi:flask-round-bottom-outline"),
        ]
    )


class NeedsTreatmentSensor(PoolEntity, BinarySensorEntity):
    """Ligado quando algum parâmetro precisa de correção."""

    _attr_device_class = BinarySensorDeviceClass.PROBLEM

    def __init__(self, manager: PoolManager) -> None:
        super().__init__(manager, "needs_treatment", "Precisa de tratamento")

    @property
    def is_on(self) -> bool | None:
        analysis = self.manager.analysis
        if not analysis.has_data:
            return None
        return analysis.needs_treatment


class MaintenancePendingSensor(PoolEntity, BinarySensorEntity):
    """Ligado quando o algicida ou o clarificante está no prazo (ou aguardando condições)."""

    def __init__(
        self, manager: PoolManager, key: str, name: str, attr: str, icon: str
    ) -> None:
        super().__init__(manager, key, name)
        self._attr = attr
        self._attr_icon = icon

    @property
    def _item(self):
        return getattr(self.manager, self._attr)

    @property
    def is_on(self) -> bool:
        return self._item.pending

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        item = self._item
        return {"situacao": item.status, "mensagem": item.message}
