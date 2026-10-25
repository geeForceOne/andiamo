"""Websocket commands for the Andiamo panel and dashboard card."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import asdict
import asyncio
from datetime import datetime, timedelta
from functools import wraps
from typing import TYPE_CHECKING, Any

import voluptuous as vol

from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.util import dt as dt_util

from .const import (
    ANNOUNCE_MODES,
    CONF_OJP_KEY,
    CONF_TOMTOM_KEY,
    DEFAULT_DEPARTURES_COUNT,
    DEFAULT_DEPARTURES_EVERY,
    DEFAULT_PROBLEM_MINUTES,
    DOMAIN,
    LANGUAGES,
    MODE_CAR,
    MODE_TRANSIT,
    SIGNAL_DATA_CHANGED,
    SIGNAL_PROBLEMS_CHANGED,
    SIGNAL_RUNS_CHANGED,
    SIGNAL_USAGE_CHANGED,
)
from .providers import lines_of
from .texts import MESSAGES, TEXTS, unknown_placeholders

if TYPE_CHECKING:
    from . import AndiamoRuntime

Handler = Callable[[HomeAssistant, "AndiamoRuntime", dict[str, Any]], Awaitable[Any]]

_OPTIONAL_STR = vol.Any(None, str)

def _hhmm(value: str) -> str:
    """A time of day as "HH:MM"."""
    try:
        return datetime.strptime(value, "%H:%M").strftime("%H:%M")
    except (TypeError, ValueError) as err:
        raise vol.Invalid(f"Unreadable time {value}") from err


LOCATION = vol.Schema(
    {
        vol.Optional("id"): str,
        vol.Required("name"): vol.All(str, vol.Length(min=1)),
        vol.Required("latitude"): vol.Coerce(float),
        vol.Required("longitude"): vol.Coerce(float),
    }
)
STATION = vol.Schema(
    {
        vol.Optional("id"): str,
        vol.Required("location_id"): str,
        vol.Required("name"): vol.All(str, vol.Length(min=1)),
        vol.Required("stop_ref"): vol.All(str, vol.Length(min=1)),
        vol.Required("walk_minutes"): vol.All(vol.Coerce(int), vol.Range(min=0, max=120)),
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
_DAYS = vol.All(
    [vol.All(vol.Coerce(int), vol.Range(min=0, max=6))], lambda days: sorted(set(days))
)
# From/until may be missing here; the store says which window needs them.
WATCH_WINDOW = vol.Schema(
    {
        vol.Required("days"): _DAYS,
        vol.Optional("from", default=None): vol.Any(None, _hhmm),
        vol.Optional("to", default=None): vol.Any(None, _hhmm),
        vol.Optional("problem_minutes", default=DEFAULT_PROBLEM_MINUTES): vol.All(
            vol.Coerce(int), vol.Range(min=1, max=180)
        ),
    }
)
DEPARTURE_WINDOW = vol.Schema(
    {
        vol.Required("days"): _DAYS,
        vol.Optional("from", default=None): vol.Any(None, _hhmm),
        vol.Optional("to", default=None): vol.Any(None, _hhmm),
        vol.Optional("every", default=DEFAULT_DEPARTURES_EVERY): vol.All(
            vol.Coerce(int), vol.Range(min=1, max=60)
        ),
        vol.Optional("count", default=DEFAULT_DEPARTURES_COUNT): vol.All(
            vol.Coerce(int), vol.Range(min=1, max=20)
        ),
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
        vol.Optional("announce", default=None): vol.Any(None, vol.In(ANNOUNCE_MODES)),
        # Car routes: minutes on top of the drive time; None = the setting.
        vol.Optional("reserve_minutes", default=None): vol.Any(
            None, vol.All(vol.Coerce(int), vol.Range(min=0, max=120))
        ),
        vol.Optional("watch_windows", default=list): [WATCH_WINDOW],
        vol.Optional("departure_windows", default=list): [DEPARTURE_WINDOW],
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
        vol.Optional("car_reserve_minutes"): vol.All(vol.Coerce(int), vol.Range(min=0, max=120)),
        vol.Optional("announce"): vol.In(ANNOUNCE_MODES),
        vol.Optional("limit_tomtom"): vol.All(vol.Coerce(int), vol.Range(min=1)),
        vol.Optional("limit_ojp"): vol.All(vol.Coerce(int), vol.Range(min=1)),
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
        **runtime.watchdog.as_dict(),
        "usage": runtime.usage.as_dict(),
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
        ws_reorder,
        ws_search_stops,
        ws_search_places,
        ws_lines,
        ws_start,
        ws_check,
        ws_cancel,
        ws_timetable,
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
        async_dispatcher_connect(hass, SIGNAL_PROBLEMS_CHANGED, send),
        async_dispatcher_connect(hass, SIGNAL_USAGE_CHANGED, send),
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


@_command("reorder", {vol.Required("kind"): vol.In(["routes", "locations"]), vol.Required("ids"): [str]})
async def ws_reorder(hass, runtime, msg):
    await runtime.store.async_reorder(msg["kind"], msg["ids"])


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


@_command("start", {vol.Required("route_id"): str, vol.Optional("arrive_at"): str})
async def ws_start(hass, runtime, msg):
    """Start a route like the andiamo.start action; car routes need `arrive_at`."""
    arrive_at = None
    if "arrive_at" in msg:
        arrive_at = dt_util.parse_datetime(msg["arrive_at"])
        if arrive_at is None:
            raise HomeAssistantError(f"Unreadable time {msg['arrive_at']}")
        if arrive_at.tzinfo is None:
            arrive_at = arrive_at.replace(tzinfo=dt_util.get_default_time_zone())
    await runtime.runs.async_start(msg["route_id"], arrive_at)


@_command("check", {vol.Required("route_id"): str})
async def ws_check(hass, runtime, msg):
    return await runtime.runs.async_check_car(msg["route_id"])


@_command("cancel", {vol.Required("route_id"): str})
async def ws_cancel(hass, runtime, msg):
    await runtime.runs.async_cancel(msg["route_id"])


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/timetable",
        vol.Optional("route_ids"): [str],
        vol.Optional("count", default=5): vol.All(vol.Coerce(int), vol.Range(min=1, max=20)),
        vol.Optional("refresh", default=60): vol.All(
            vol.Coerce(int), vol.Range(min=30, max=300)
        ),
    }
)
@callback
def ws_timetable(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Departure boards and car drive times for the card, now and every `refresh` seconds while it's open."""
    try:
        runtime = _runtime(hass)
    except HomeAssistantError as err:
        connection.send_error(msg["id"], "not_loaded", str(err))
        return
    refresh = timedelta(seconds=msg["refresh"])
    task: asyncio.Task[None] | None = None

    async def send() -> None:
        boards = await runtime.timetable.boards(msg.get("route_ids"), msg["count"], refresh)
        connection.send_message(websocket_api.event_message(msg["id"], {"boards": boards}))

    @callback
    def update(*_: Any) -> None:
        nonlocal task
        if task is None or task.done():
            task = hass.async_create_background_task(send(), f"{DOMAIN}_timetable")

    unsubs = [
        async_track_time_interval(hass, update, refresh),
        async_dispatcher_connect(hass, SIGNAL_DATA_CHANGED, update),
    ]

    @callback
    def unsubscribe() -> None:
        for unsub in unsubs:
            unsub()
        if task is not None:
            task.cancel()

    connection.subscriptions[msg["id"]] = unsubscribe
    connection.send_result(msg["id"])
    update()
