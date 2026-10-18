"""Config flow: just the API keys; everything else is in the Andiamo panel."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.helpers.selector import (
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .const import CONF_OJP_KEY, CONF_TOMTOM_KEY, DOMAIN

_KEY = TextSelector(TextSelectorConfig(type=TextSelectorType.PASSWORD))


def _schema(defaults: dict[str, Any]) -> vol.Schema:
    return vol.Schema(
        {
            vol.Optional(
                CONF_OJP_KEY, default=defaults.get(CONF_OJP_KEY, "")
            ): _KEY,
            vol.Optional(
                CONF_TOMTOM_KEY, default=defaults.get(CONF_TOMTOM_KEY, "")
            ): _KEY,
        }
    )


def _clean(user_input: dict[str, Any]) -> dict[str, str]:
    return {key: value.strip() for key, value in user_input.items() if value.strip()}


class AndiamoConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            data = _clean(user_input)
            if data:
                return self.async_create_entry(title="Andiamo", data=data)
            errors["base"] = "no_keys"
        return self.async_show_form(
            step_id="user", data_schema=_schema(user_input or {}), errors=errors
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            data = _clean(user_input)
            if data:
                return self.async_update_reload_and_abort(entry, data=data)
            errors["base"] = "no_keys"
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=_schema(user_input or dict(entry.data)),
            errors=errors,
        )
