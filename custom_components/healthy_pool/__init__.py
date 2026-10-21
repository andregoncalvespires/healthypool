"""Healthy Pool: volume, qualidade da água e dosagem de produtos Genco."""
from __future__ import annotations

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.typing import ConfigType
from homeassistant.util import dt as dt_util

from .const import DOMAIN, SERVICE_RECORD_MEASUREMENT, SERVICE_RECORD_STEP
from .pool import PoolManager

PLATFORMS: list[Platform] = [
    Platform.NUMBER,
    Platform.DATETIME,
    Platform.SELECT,
    Platform.SENSOR,
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
]

SERVICE_SCHEMA = vol.Schema(
    {
        vol.Optional("entry_id"): cv.string,
        vol.Optional("alcalinidade"): vol.Coerce(float),
        vol.Optional("ph"): vol.Coerce(float),
        vol.Optional("cloro"): vol.Coerce(float),
        vol.Optional("data_medicao"): cv.datetime,
    }
)


STEP_SCHEMA = vol.Schema(
    {
        vol.Optional("entry_id"): cv.string,
        vol.Optional("produto"): cv.string,
        vol.Optional("quantidade"): vol.All(vol.Coerce(float), vol.Range(min=0)),
    }
)


def _get_manager(hass: HomeAssistant, entry_id: str | None) -> PoolManager:
    managers: dict[str, PoolManager] = hass.data.get(DOMAIN, {})
    if entry_id:
        manager = managers.get(entry_id)
    elif len(managers) == 1:
        manager = next(iter(managers.values()))
    else:
        manager = None
    if manager is None:
        raise ServiceValidationError(
            "Piscina não encontrada: informe entry_id quando houver mais de uma."
        )
    return manager


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Registra os serviços healthy_pool.registrar_medicao e healthy_pool.registrar_etapa."""

    async def _record(call: ServiceCall) -> None:
        manager = _get_manager(hass, call.data.get("entry_id"))
        kwargs: dict[str, object] = {}
        for field, attr in (("alcalinidade", "alkalinity"), ("ph", "ph"), ("cloro", "chlorine")):
            if field in call.data:
                kwargs[attr] = call.data[field]
        if "data_medicao" in call.data:
            kwargs["measured_at"] = dt_util.as_local(call.data["data_medicao"])
        manager.set_measurement(**kwargs)

    async def _record_step(call: ServiceCall) -> None:
        manager = _get_manager(hass, call.data.get("entry_id"))
        product = call.data.get("produto")
        key = manager.resolve_product(product) if product else None
        if product and key is None:
            raise ServiceValidationError(f"Produto desconhecido: {product}")
        manager.register_step(key=key, amount=call.data.get("quantidade"))

    hass.services.async_register(
        DOMAIN, SERVICE_RECORD_MEASUREMENT, _record, schema=SERVICE_SCHEMA
    )
    hass.services.async_register(
        DOMAIN, SERVICE_RECORD_STEP, _record_step, schema=STEP_SCHEMA
    )
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    manager = PoolManager(hass, entry)
    await manager.async_load()
    manager.async_start()
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = manager

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        manager: PoolManager = hass.data[DOMAIN].pop(entry.entry_id)
        manager.async_stop()
    return unloaded


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)
