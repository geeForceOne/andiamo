"""Websocket commands for the Andiamo panel and dashboard card."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import asdict
from functools import wraps
from typing import TYPE_CHECKING, Any

import voluptuous as vol

from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.util import dt as dt_util

from .const import (
    CONF_OJP_KEY,
    CONF_TOMTOM_KEY,
    DOMAIN,
    LANGUAGES,
    MODE_CAR,
    MODE_TRANSIT,
    SIGNAL_DATA_CHANGED,
    SIGNAL_RUNS_CHANGED,
)
from .providers import lines_of
from .texts import MESSAGES, TEXTS, unknown_placeholders

if TYPE_CHECKING:
    from . import AndiamoRuntime

Handler = Callable[[HomeAssistant, "AndiamoRuntime", dict[str, Any]], Awaitable[Any]]

_OPTIONAL_STR = vol.Any(None, str)

LOCATION = vol.Schema(
    {
        vol.Optional("id"): str,
        vol.Required("name"): vol.All(str, vol.Length(min=1)),
        vol.Required("latitude"): vol.Coerce(float),
        vol.Required("longitude"): vol.Coerce(float),
        vol.Optional("main"): bool,
    }
)
STATION = vol.Schema(
    {
        vol.Optional("id"): str,
        vol.Required("location_id"): str,
        vol.Required("name"): vol.All(str, vol.Length(min=1)),
        vol.Required("stop_ref"): vol.All(str, vol.Length(min=1)),
        vol.Required("walk_minutes"): vol.All(vol.Coerce(int), vol.Range(min=0, max=120)),
        vol.Optional("main"): bool,
    }
)
LINE = vol.Schema(
    {
        vol.Required("key"): vol.All(str, vol.Length(min=1)),
        vol.Required("name"): str,
        vol.Required("destination"): str,
        vol.Optional("mode", default=""): str,
    }
)
ROUTE = vol.Schema(
    {
        vol.Optional("id"): str,
        vol.Required("name"): vol.All(str, vol.Length(min=1)),
        vol.Required("mode"): vol.In([MODE_TRANSIT, MODE_CAR]),
        vol.Required("origin_id"): str,
        vol.Optional("destination_id", default=None): _OPTIONAL_STR,
        vol.Optional("station_id", default=None): _OPTIONAL_STR,
        vol.Optional("lines", default=list): [LINE],
        vol.Optional("speaker", default=None): _OPTIONAL_STR,
    }
)
def _template(value: str) -> str:
    if unknown := unknown_placeholders(value):
        raise vol.Invalid(f"Unknown placeholder: {', '.join(unknown)}")
    return value


SETTINGS = vol.Schema(
    {
        vol.Optional("tts_entity"): _OPTIONAL_STR,
        vol.Optional("speaker"): _OPTIONAL_STR,
        vol.Optional("language"): vol.In(LANGUAGES),
        vol.Optional("car_lead_minutes"): vol.All(vol.Coerce(int), vol.Range(min=5, max=180)),
        vol.Optional("test_mode"): bool,
        vol.Optional("templates"): {vol.In(LANGUAGES): {vol.In(MESSAGES): vol.All(str, _template)}},
    }
)


def _runtime(hass: HomeAssistant) -> AndiamoRuntime:
    runtime = hass.data.get(DOMAIN)
    if runtime is None:
        raise HomeAssistantError("Andiamo is not set up")
    return runtime


def _state(runtime: AndiamoRuntime) -> dict[str, Any]:
    return {
        **runtime.store.as_dict(),
        "runs": runtime.runs.as_list(),
        "messages": {lang: {key: TEXTS[lang][key] for key in MESSAGES} for lang in LANGUAGES},
        "providers": {
            MODE_TRANSIT: bool(runtime.entry.data.get(CONF_OJP_KEY)),
            MODE_CAR: bool(runtime.entry.data.get(CONF_TOMTOM_KEY)),
        },
    }


def _command(name: str, schema: dict[Any, Any]) -> Callable[[Handler], Any]:
    """A command that answers with the handler's result or the error message."""

    def wrap(handler: Handler) -> Any:
        @websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/{name}", **schema})
        @websocket_api.async_response
        @wraps(handler)
        async def run(
            hass: HomeAssistant,
            connection: websocket_api.ActiveConnection,
            msg: dict[str, Any],
        ) -> None:
            try:
                result = await handler(hass, _runtime(hass), msg)
            except HomeAssistantError as err:
                connection.send_error(msg["id"], "failed", str(err))
                return
            connection.send_result(msg["id"], result)

        return run

    return wrap


@callback
def async_register(hass: HomeAssistant) -> None:
    for command in (
        ws_subscribe,
        ws_settings,
        ws_save_location,
        ws_delete_location,
        ws_save_station,
        ws_delete_station,
        ws_save_route,
        ws_delete_route,
        ws_search_stops,
        ws_search_places,
        ws_lines,
        ws_press,
        ws_start_car,
        ws_cancel,
    ):
        websocket_api.async_register_command(hass, command)


@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/subscribe"})
@callback
def ws_subscribe(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Send everything now and again after every change."""
    try:
        runtime = _runtime(hass)
    except HomeAssistantError as err:
        connection.send_error(msg["id"], "not_loaded", str(err))
        return

    @callback
    def send() -> None:
        connection.send_message(websocket_api.event_message(msg["id"], _state(runtime)))

    unsubs = [
        async_dispatcher_connect(hass, SIGNAL_DATA_CHANGED, send),
        async_dispatcher_connect(hass, SIGNAL_RUNS_CHANGED, send),
    ]

    @callback
    def unsubscribe() -> None:
        for unsub in unsubs:
            unsub()

    connection.subscriptions[msg["id"]] = unsubscribe
    connection.send_result(msg["id"])
    send()


@_command("settings", {vol.Required("changes"): SETTINGS})
async def ws_settings(hass, runtime, msg):
    await runtime.store.async_update_settings(msg["changes"])


@_command("location/save", {vol.Required("item"): LOCATION})
async def ws_save_location(hass, runtime, msg):
    return await runtime.store.async_save_location(msg["item"])


@_command("location/delete", {vol.Required("item_id"): str})
async def ws_delete_location(hass, runtime, msg):
    await runtime.store.async_delete_location(msg["item_id"])


@_command("station/save", {vol.Required("item"): STATION})
async def ws_save_station(hass, runtime, msg):
    return await runtime.store.async_save_station(msg["item"])


@_command("station/delete", {vol.Required("item_id"): str})
async def ws_delete_station(hass, runtime, msg):
    await runtime.store.async_delete_station(msg["item_id"])


@_command("route/save", {vol.Required("item"): ROUTE})
async def ws_save_route(hass, runtime, msg):
    return await runtime.store.async_save_route(msg["item"])


@_command("route/delete", {vol.Required("item_id"): str})
async def ws_delete_route(hass, runtime, msg):
    await runtime.runs.async_cancel(msg["item_id"], say=False)
    await runtime.store.async_delete_route(msg["item_id"])


@_command("search_stops", {vol.Required("query"): str})
async def ws_search_stops(hass, runtime, msg):
    return [asdict(stop) for stop in await runtime.transit().search_stops(msg["query"])]


@_command("search_places", {vol.Required("query"): str})
async def ws_search_places(hass, runtime, msg):
    return [asdict(place) for place in await runtime.car().search_places(msg["query"])]


@_command("lines", {vol.Required("station_id"): str})
async def ws_lines(hass, runtime, msg):
    """The lines leaving a station in the next hours, for the route form."""
    station = runtime.store.station(msg["station_id"])
    departures = await runtime.transit().departures(station["stop_ref"], dt_util.utcnow())
    return [asdict(line) for line in lines_of(departures)]


@_command("press", {vol.Required("route_id"): str})
async def ws_press(hass, runtime, msg):
    await runtime.runs.async_press(msg["route_id"])


@_command("start_car", {vol.Required("route_id"): str, vol.Required("arrive_at"): str})
async def ws_start_car(hass, runtime, msg):
    arrive_at = dt_util.parse_datetime(msg["arrive_at"])
    if arrive_at is None:
        raise HomeAssistantError(f"Unreadable time {msg['arrive_at']}")
    if arrive_at.tzinfo is None:
        arrive_at = arrive_at.replace(tzinfo=dt_util.get_default_time_zone())
    await runtime.runs.async_start_car(msg["route_id"], arrive_at)


@_command("cancel", {vol.Required("route_id"): str})
async def ws_cancel(hass, runtime, msg):
    await runtime.runs.async_cancel(msg["route_id"])
