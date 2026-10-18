"""Config flow: API keys only."""

from __future__ import annotations

from unittest.mock import patch

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.andiamo.const import CONF_OJP_KEY, CONF_TOMTOM_KEY, DOMAIN


async def test_needs_a_key(hass: HomeAssistant) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_OJP_KEY: " ", CONF_TOMTOM_KEY: ""}
    )
    assert result["errors"] == {"base": "no_keys"}

    with patch("custom_components.andiamo.async_setup_entry", return_value=True):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_OJP_KEY: " abc ", CONF_TOMTOM_KEY: ""}
        )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == {CONF_OJP_KEY: "abc"}


async def test_reconfigure(hass: HomeAssistant) -> None:
    entry = MockConfigEntry(domain=DOMAIN, data={CONF_OJP_KEY: "abc"})
    entry.add_to_hass(hass)
    result = await entry.start_reconfigure_flow(hass)
    assert result["type"] is FlowResultType.FORM

    with patch("custom_components.andiamo.async_setup_entry", return_value=True):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_OJP_KEY: "abc", CONF_TOMTOM_KEY: "tt"}
        )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert entry.data == {CONF_OJP_KEY: "abc", CONF_TOMTOM_KEY: "tt"}
