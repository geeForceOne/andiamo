"""Andiamo: tells you when to leave, by public transport or by car."""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
from pathlib import Path

import voluptuous as vol

from homeassistant.components import frontend, panel_custom
from homeassistant.components.http import StaticPathConfig
from homeassistant.components.sensor import DOMAIN as SENSOR_DOMAIN
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv, service
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.typing import ConfigType

from . import websocket
from .announcer import Announcer
from .const import (
    CONF_OJP_KEY,
    CONF_TOMTOM_KEY,
    DOMAIN,
    PANEL_COMPONENT,
    PANEL_URL_PATH,
    STATIC_URL,
)
from .providers import CarProvider, TransitProvider
from .providers.ojp import OjpProvider
from .providers.tomtom import TomTomProvider
from .runner import RunManager
from .store import DataError, AndiamoStore

PLATFORMS = [Platform.BUTTON, Platform.SENSOR]
FRONTEND_DIR = Path(__file__).parent / "www"

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


@dataclass
class AndiamoRuntime:
    store: AndiamoStore
    entry: ConfigEntry
    runs: RunManager = field(init=False)

    def transit(self) -> TransitProvider:
        key = self.entry.data.get(CONF_OJP_KEY)
        if not key:
            raise DataError("No opentransportdata.swiss API key set")
        session = async_get_clientsession(self.store.hass)
        return OjpProvider(session, key, self.store.settings.get("language", "de"))

    def car(self) -> CarProvider:
        key = self.entry.data.get(CONF_TOMTOM_KEY)
        if not key:
            raise DataError("No TomTom API key set")
        hass = self.store.hass
        return TomTomProvider(
            async_get_clientsession(hass),
            key,
            self.store.settings.get("language", "de"),
            bias=(hass.config.latitude, hass.config.longitude),
        )


type AndiamoConfigEntry = ConfigEntry[AndiamoRuntime]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Websocket commands and the frontend files, once per HA start."""
    websocket.async_register(hass)
    # Actions on a route's "leave at" sensor, for automations and scripts.
    service.async_register_platform_entity_service(
        hass,
        DOMAIN,
        "start",
        entity_domain=SENSOR_DOMAIN,
        schema={
            vol.Optional("time"): cv.time,
            vol.Optional("date"): cv.date,
            vol.Optional("speaker"): cv.entity_domain("media_player"),
        },
        func="async_start_route",
    )
    service.async_register_platform_entity_service(
        hass, DOMAIN, "stop", entity_domain=SENSOR_DOMAIN, schema=None, func="async_stop_route"
    )
    await hass.http.async_register_static_paths(
        [StaticPathConfig(STATIC_URL, str(FRONTEND_DIR), cache_headers=False)]
    )
    # The dashboard card is available without adding a resource by hand.
    card_url = await hass.async_add_executor_job(_file_url, "andiamo-card.js")
    frontend.add_extra_js_url(hass, card_url)
    return True


def _file_url(name: str) -> str:
    """URL with a fingerprint of the file, so browsers load every changed version."""
    digest = hashlib.sha256((FRONTEND_DIR / name).read_bytes()).hexdigest()[:12]
    return f"{STATIC_URL}/{name}?v={digest}"


async def async_setup_entry(hass: HomeAssistant, entry: AndiamoConfigEntry) -> bool:
    store = AndiamoStore(hass)
    await store.async_load()
    runtime = AndiamoRuntime(store=store, entry=entry)
    runtime.runs = RunManager(
        hass, store, Announcer(hass, store), runtime.transit, runtime.car
    )
    entry.runtime_data = runtime
    hass.data[DOMAIN] = runtime

    await panel_custom.async_register_panel(
        hass,
        webcomponent_name=PANEL_COMPONENT,
        frontend_url_path=PANEL_URL_PATH,
        module_url=await hass.async_add_executor_job(_file_url, "andiamo-panel.js"),
        sidebar_title="Andiamo",
        sidebar_icon="mdi:clock-fast",
        require_admin=False,
    )
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_create_background_task(
        hass, runtime.runs.async_resume(), f"{DOMAIN}_resume"
    )
    return True


async def async_unload_entry(hass: HomeAssistant, entry: AndiamoConfigEntry) -> bool:
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        entry.runtime_data.runs.stop_all()
        frontend.async_remove_panel(hass, PANEL_URL_PATH)
        hass.data.pop(DOMAIN, None)
    return unloaded
