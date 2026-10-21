"""Entradas manuais das medições (kit de gotas)."""
from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .entity import PoolEntity
from .pool import PoolManager
from .treatment import PRODUCTS


@dataclass(frozen=True)
class _Spec:
    key: str
    name: str
    attr: str
    icon: str
    unit: str
    min: float
    max: float
    step: float


SPECS = (
    _Spec("alkalinity", "Alcalinidade total", "alkalinity", "mdi:test-tube", "ppm", 0, 300, 1),
    _Spec("ph", "pH", "ph", "mdi:ph", "", 5.0, 9.0, 0.1),
    _Spec("chlorine", "Cloro livre", "chlorine", "mdi:chemical-weapon", "ppm", 0, 10, 0.1),
)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    manager: PoolManager = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [
            *(PoolMeasurementNumber(manager, spec) for spec in SPECS),
            PoolFreeboardNumber(manager),
            PoolMetalsNumber(manager),
            PoolAppliedAmountNumber(manager),
        ]
    )


class PoolMeasurementNumber(PoolEntity, NumberEntity):
    """Medição manual (alcalinidade, pH ou cloro)."""

    _attr_mode = NumberMode.BOX

    def __init__(self, manager: PoolManager, spec: _Spec) -> None:
        super().__init__(manager, spec.key, spec.name)
        self._spec = spec
        self._attr_icon = spec.icon
        self._attr_native_min_value = spec.min
        self._attr_native_max_value = spec.max
        self._attr_native_step = spec.step
        self._attr_native_unit_of_measurement = spec.unit or None

    @property
    def native_value(self) -> float | None:
        return getattr(self.manager, self._spec.attr)

    async def async_set_native_value(self, value: float) -> None:
        self.manager.set_measurement(**{self._spec.attr: value})


class PoolFreeboardNumber(PoolEntity, NumberEntity):
    """Altura livre: distância da lâmina de água até a borda (ajuste conforme o nível)."""

    _attr_mode = NumberMode.BOX
    _attr_icon = "mdi:waves-arrow-up"
    _attr_native_min_value = 0
    _attr_native_max_value = 30
    _attr_native_step = 0.5
    _attr_native_unit_of_measurement = "cm"

    def __init__(self, manager: PoolManager) -> None:
        super().__init__(manager, "freeboard", "Altura livre")

    @property
    def native_value(self) -> float:
        return self.manager.freeboard_cm

    async def async_set_native_value(self, value: float) -> None:
        self.manager.set_freeboard(value)


class PoolMetalsNumber(PoolEntity, NumberEntity):
    """Metais dissolvidos (ferro, manganês, cobre) de um teste. 0 = não medido."""

    _attr_mode = NumberMode.BOX
    _attr_icon = "mdi:flask-round-bottom-outline"
    _attr_native_min_value = 0
    _attr_native_max_value = 10
    _attr_native_step = 0.1
    _attr_native_unit_of_measurement = "ppm"

    def __init__(self, manager: PoolManager) -> None:
        super().__init__(manager, "metals_ppm", "Metais dissolvidos")

    @property
    def native_value(self) -> float:
        return self.manager.metals_ppm

    async def async_set_native_value(self, value: float) -> None:
        self.manager.set_metals_ppm(value)


class PoolAppliedAmountNumber(PoolEntity, NumberEntity):
    """Quantidade realmente aplicada (já vem com a dose sugerida)."""

    _attr_mode = NumberMode.BOX
    _attr_icon = "mdi:scale"
    _attr_native_min_value = 0
    _attr_native_max_value = 100000
    _attr_native_step = 1

    def __init__(self, manager: PoolManager) -> None:
        super().__init__(manager, "applied_amount", "Quantidade aplicada")

    @property
    def native_unit_of_measurement(self) -> str | None:
        key = self.manager.effective_product
        return PRODUCTS[key].unit if key else None

    @property
    def native_value(self) -> float:
        return round(self.manager.effective_amount)

    async def async_set_native_value(self, value: float) -> None:
        self.manager.select_amount(value)
