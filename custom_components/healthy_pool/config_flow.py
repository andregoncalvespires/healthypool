"""Configuração pela interface do Home Assistant."""
from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow, OptionsFlow
from homeassistant.core import callback
from homeassistant.helpers import selector

from .catalog import (
    BUILTIN_DIR,
    CONF_PRODUCT_PREFIX,
    DEFAULT_IDS,
    ROLE_ORDER,
    Product,
    load_products,
    products_for_role,
)
from .const import (
    CONF_ALGAECIDE_DAYS,
    CONF_ALK_MAX,
    CONF_ALK_MIN,
    CONF_ALK_TARGET,
    CONF_CL_MAX,
    CONF_CLARIFIER_DAYS,
    CONF_CL_MIN,
    CONF_CL_TARGET,
    CONF_DEEP_DEPTH,
    CONF_LENGTH,
    CONF_NAME,
    CONF_PH_MAX,
    CONF_PH_MIN,
    CONF_PH_TARGET,
    CONF_PH_UP_FACTOR,
    CONF_SHALLOW_DEPTH,
    CONF_SHALLOW_LENGTH,
    CONF_STAIR_STEPS,
    CONF_STAIR_TREAD,
    CONF_STAIR_WIDTH,
    CONF_SHAPE,
    CONF_MANUAL_VOLUME,
    SHAPES,
    SHAPE_MANUAL,
    SHAPE_RECT,
    SHAPE_SLOPED,
    CONF_TEMP_ENTITY,
    CONF_WIDTH,
    DEFAULT_NAME,
    DEFAULTS,
    DOMAIN,
    USER_PRODUCTS_DIRNAME,
)


def _num(min_: float, max_: float, step: float, unit: str | None = None):
    config: dict[str, Any] = {
        "min": min_,
        "max": max_,
        "step": step,
        "mode": selector.NumberSelectorMode.BOX,
    }
    if unit:
        config["unit_of_measurement"] = unit
    return selector.NumberSelector(selector.NumberSelectorConfig(**config))


def _geometry_schema(values: dict[str, Any], with_name: bool) -> vol.Schema:
    fields: dict[Any, Any] = {}
    if with_name:
        fields[vol.Required(CONF_NAME, default=values.get(CONF_NAME, DEFAULT_NAME))] = str
    fields.update(
        {
            vol.Required(CONF_SHAPE, default=values[CONF_SHAPE]): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=list(SHAPES),
                    translation_key=CONF_SHAPE,
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            ),
            vol.Required(CONF_MANUAL_VOLUME, default=values[CONF_MANUAL_VOLUME]): _num(0, 1000, 0.1, "m³"),
            vol.Required(CONF_LENGTH, default=values[CONF_LENGTH]): _num(0, 3000, 1, "cm"),
            vol.Required(CONF_WIDTH, default=values[CONF_WIDTH]): _num(0, 3000, 1, "cm"),
            vol.Required(CONF_SHALLOW_LENGTH, default=values[CONF_SHALLOW_LENGTH]): _num(0, 3000, 1, "cm"),
            vol.Required(CONF_SHALLOW_DEPTH, default=values[CONF_SHALLOW_DEPTH]): _num(0, 300, 1, "cm"),
            vol.Required(CONF_DEEP_DEPTH, default=values[CONF_DEEP_DEPTH]): _num(0, 500, 1, "cm"),
            vol.Required(CONF_STAIR_STEPS, default=values[CONF_STAIR_STEPS]): _num(0, 10, 1),
            vol.Required(CONF_STAIR_TREAD, default=values[CONF_STAIR_TREAD]): _num(0, 100, 1, "cm"),
            vol.Required(CONF_STAIR_WIDTH, default=values[CONF_STAIR_WIDTH]): _num(0, 1000, 1, "cm"),
            vol.Optional(
                CONF_TEMP_ENTITY,
                description={"suggested_value": values.get(CONF_TEMP_ENTITY)},
            ): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="sensor", device_class="temperature")
            ),
        }
    )
    return vol.Schema(fields)


async def _load_catalog(hass) -> dict[str, Product]:
    return await hass.async_add_executor_job(
        load_products, [BUILTIN_DIR, hass.config.path(USER_PRODUCTS_DIRNAME)]
    )


def _products_schema(catalog: dict[str, Product], values: dict[str, Any]) -> vol.Schema:
    fields: dict[Any, Any] = {}
    for role in ROLE_ORDER:
        options = [
            selector.SelectOptionDict(value=p.id, label=p.label)
            for p in products_for_role(catalog, role)
        ]
        key = f"{CONF_PRODUCT_PREFIX}{role}"
        current = values.get(key)
        if current not in {o["value"] for o in options}:
            current = DEFAULT_IDS[role]
        fields[vol.Required(key, default=current)] = selector.SelectSelector(
            selector.SelectSelectorConfig(options=options, mode=selector.SelectSelectorMode.DROPDOWN)
        )
    return vol.Schema(fields)


def _limits_schema(values: dict[str, Any]) -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(CONF_ALK_MIN, default=values[CONF_ALK_MIN]): _num(0, 300, 1, "ppm"),
            vol.Required(CONF_ALK_TARGET, default=values[CONF_ALK_TARGET]): _num(0, 300, 1, "ppm"),
            vol.Required(CONF_ALK_MAX, default=values[CONF_ALK_MAX]): _num(0, 300, 1, "ppm"),
            vol.Required(CONF_PH_MIN, default=values[CONF_PH_MIN]): _num(6, 9, 0.1),
            vol.Required(CONF_PH_TARGET, default=values[CONF_PH_TARGET]): _num(6, 9, 0.1),
            vol.Required(CONF_PH_MAX, default=values[CONF_PH_MAX]): _num(6, 9, 0.1),
            vol.Required(CONF_CL_MIN, default=values[CONF_CL_MIN]): _num(0, 10, 0.1, "ppm"),
            vol.Required(CONF_CL_TARGET, default=values[CONF_CL_TARGET]): _num(0, 10, 0.1, "ppm"),
            vol.Required(CONF_CL_MAX, default=values[CONF_CL_MAX]): _num(0, 10, 0.1, "ppm"),
            vol.Required(CONF_PH_UP_FACTOR, default=values[CONF_PH_UP_FACTOR]): _num(0.3, 3, 0.05),
            vol.Required(CONF_ALGAECIDE_DAYS, default=values[CONF_ALGAECIDE_DAYS]): _num(1, 60, 1, "dias"),
            vol.Required(CONF_CLARIFIER_DAYS, default=values[CONF_CLARIFIER_DAYS]): _num(1, 60, 1, "dias"),
        }
    )


def _geometry_errors(d: dict[str, Any]) -> dict[str, str]:
    shape = d.get(CONF_SHAPE, SHAPE_RECT)
    if shape == SHAPE_MANUAL:
        return {} if d[CONF_MANUAL_VOLUME] > 0 else {"base": "invalid_geometry"}
    bad = d[CONF_LENGTH] <= 0 or d[CONF_DEEP_DEPTH] <= 0
    if shape == "oval":
        bad = bad or d[CONF_WIDTH] <= 0
    elif shape in (SHAPE_RECT, SHAPE_SLOPED):
        bad = bad or d[CONF_WIDTH] <= 0 or d[CONF_DEEP_DEPTH] < d[CONF_SHALLOW_DEPTH]
    if shape == SHAPE_RECT and not bad:
        steps = int(d[CONF_STAIR_STEPS])
        bad = (
            d[CONF_SHALLOW_LENGTH] >= d[CONF_LENGTH]
            or steps * d[CONF_STAIR_TREAD] > d[CONF_SHALLOW_LENGTH]
            or d[CONF_STAIR_WIDTH] > d[CONF_WIDTH]
        )
    return {"base": "invalid_geometry"} if bad else {}


def _limits_errors(d: dict[str, Any]) -> dict[str, str]:
    bad = (
        not d[CONF_ALK_MIN] < d[CONF_ALK_TARGET] < d[CONF_ALK_MAX]
        or not d[CONF_PH_MIN] < d[CONF_PH_TARGET] < d[CONF_PH_MAX]
        or not d[CONF_CL_MIN] < d[CONF_CL_TARGET] < d[CONF_CL_MAX]
    )
    return {"base": "invalid_limits"} if bad else {}


def _clean(user_input: dict[str, Any]) -> dict[str, Any]:
    out = dict(user_input)
    out[CONF_STAIR_STEPS] = int(out[CONF_STAIR_STEPS])
    out[CONF_TEMP_ENTITY] = out.get(CONF_TEMP_ENTITY) or None
    return out


class HealthyPoolConfigFlow(ConfigFlow, domain=DOMAIN):
    """Fluxo de configuração inicial."""

    VERSION = 1

    def __init__(self) -> None:
        self._data: dict[str, Any] = {}

    async def async_step_user(self, user_input: dict[str, Any] | None = None):
        errors: dict[str, str] = {}
        values = {**DEFAULTS, CONF_NAME: DEFAULT_NAME}
        if user_input is not None:
            values.update(user_input)
            errors = _geometry_errors(user_input)
            if not errors:
                self._data = _clean(user_input)
                return await self.async_step_products()
        return self.async_show_form(
            step_id="user",
            data_schema=_geometry_schema(values, with_name=True),
            errors=errors,
        )

    async def async_step_products(self, user_input: dict[str, Any] | None = None):
        catalog = await _load_catalog(self.hass)
        if user_input is not None:
            self._data = {**self._data, **user_input}
            return await self.async_step_limits()
        return self.async_show_form(
            step_id="products", data_schema=_products_schema(catalog, dict(DEFAULTS))
        )

    async def async_step_limits(self, user_input: dict[str, Any] | None = None):
        errors: dict[str, str] = {}
        values = dict(DEFAULTS)
        if user_input is not None:
            values.update(user_input)
            errors = _limits_errors(user_input)
            if not errors:
                data = {**self._data, **user_input}
                return self.async_create_entry(title=data[CONF_NAME], data=data)
        return self.async_show_form(
            step_id="limits", data_schema=_limits_schema(values), errors=errors
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return HealthyPoolOptionsFlow()


class HealthyPoolOptionsFlow(OptionsFlow):
    """Ajustes depois da instalação (geometria, altura livre e faixas)."""

    def __init__(self) -> None:
        self._geometry: dict[str, Any] = {}

    def _current(self) -> dict[str, Any]:
        return {**DEFAULTS, **self.config_entry.data, **self.config_entry.options}

    async def async_step_init(self, user_input: dict[str, Any] | None = None):
        errors: dict[str, str] = {}
        values = self._current()
        if user_input is not None:
            values.update(user_input)
            errors = _geometry_errors(user_input)
            if not errors:
                self._geometry = _clean(user_input)
                return await self.async_step_products()
        return self.async_show_form(
            step_id="init",
            data_schema=_geometry_schema(values, with_name=False),
            errors=errors,
        )

    async def async_step_products(self, user_input: dict[str, Any] | None = None):
        catalog = await _load_catalog(self.hass)
        if user_input is not None:
            self._geometry = {**self._geometry, **user_input}
            return await self.async_step_limits()
        return self.async_show_form(
            step_id="products", data_schema=_products_schema(catalog, self._current())
        )

    async def async_step_limits(self, user_input: dict[str, Any] | None = None):
        errors: dict[str, str] = {}
        values = self._current()
        if user_input is not None:
            values.update(user_input)
            errors = _limits_errors(user_input)
            if not errors:
                return self.async_create_entry(data={**self._geometry, **user_input})
        return self.async_show_form(
            step_id="limits", data_schema=_limits_schema(values), errors=errors
        )
