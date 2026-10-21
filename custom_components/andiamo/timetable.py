"""Departure boards for the timetable card and the departure sensors, fetched only while needed."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import datetime, timedelta
import logging
from typing import Any

from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect, async_dispatcher_send
from homeassistant.helpers.event import async_track_time_change
from homeassistant.util import dt as dt_util

from .const import MODE_TRANSIT, SIGNAL_BOARDS_CHANGED, SIGNAL_DATA_CHANGED
from .providers import Departure, TransitProvider
from .store import AndiamoStore
from .texts import clock, minutes_until, short_minutes
from .windows import active

_LOGGER = logging.getLogger(__name__)
# A cached board is reused when it's at most this much younger than asked, so a
# fetch every N minutes doesn't slip to N+1 because the timer fired a bit early.
SLACK = timedelta(seconds=5)


class Timetable:
    """Departures per station, shared by every open card that shows the station."""

    def __init__(self, store: AndiamoStore, transit: Callable[[], TransitProvider]) -> None:
        self.store = store
        self.transit = transit
        # {stop_ref: (fetched_at, departures)}
        self._cache: dict[str, tuple[datetime, list[Departure]]] = {}
        self._pending: dict[str, asyncio.Future[list[Departure]]] = {}

    async def departures(self, stop_ref: str, max_age: timedelta) -> list[Departure]:
        """The station's departures, from a call another card made just before if there was one."""
        cached = self._cache.get(stop_ref)
        if cached and dt_util.utcnow() - cached[0] < max_age:
            return cached[1]
        if (pending := self._pending.get(stop_ref)) is not None:
            return await pending
        future: asyncio.Future[list[Departure]] = asyncio.get_running_loop().create_future()
        self._pending[stop_ref] = future
        try:
            found = await self.transit().departures(
                stop_ref, dt_util.utcnow(), include_cancelled=True
            )
        except Exception as err:
            future.set_exception(err)
            # Nobody else may be waiting; don't warn about an exception nobody reads.
            future.exception()
            raise
        else:
            self._cache[stop_ref] = (dt_util.utcnow(), found)
            future.set_result(found)
            return found
        finally:
            del self._pending[stop_ref]

    async def boards(
        self, route_ids: list[str] | None, count: int, refresh: timedelta
    ) -> list[dict[str, Any]]:
        """For each transit route: its station and next departures on its ticked lines."""
        routes = [
            r
            for r in self.store.routes
            if r["mode"] == MODE_TRANSIT and (not route_ids or r["id"] in route_ids)
        ]
        boards = []
        for route in routes:
            board: dict[str, Any] = {"route_id": route["id"], "name": route["name"]}
            boards.append(board)
            if not route.get("lines"):
                board["error"] = f"Pick a line for {route['name']}"
                continue
            station = self.store.route_station(route)
            walk = timedelta(minutes=station.get("walk_minutes", 0))
            keys = {line["key"] for line in route["lines"]}
            board.update(station=station["name"], walk_minutes=station.get("walk_minutes", 0))
            try:
                found = await self.departures(station["stop_ref"], refresh - SLACK)
            except Exception as err:  # noqa: BLE001 - one station failing mustn't empty the card
                board["error"] = str(err) or type(err).__name__
                continue
            now = dt_util.utcnow()
            # A few more than asked, so the card can drop the ones missed until the next refresh.
            catchable = sorted(
                (d for d in found if d.line_key in keys and d.departure - walk >= now),
                key=lambda d: d.departure,
            )
            board["departures"] = [_departure(d, walk) for d in catchable[: count + 3]]
        return boards


def _departure(d: Departure, walk: timedelta) -> dict[str, Any]:
    delay = round(d.delay.total_seconds() / 60)
    return {
        "line": d.line,
        "destination": d.destination,
        "mode": d.mode,
        "departure": d.departure.isoformat(),
        "planned_departure": d.planned_departure.isoformat(),
        "leave_at": (d.departure - walk).isoformat(),
        "delay_minutes": delay,
        "cancelled": d.cancelled,
        # Short enough for a pixel clock: "14 Bahnhofplatz/HB 17:54 +1".
        "text": f"{d.line} {d.destination} {clock(d.departure)}"
        + (" cancelled" if d.cancelled else f" +{delay}" if delay > 0 else ""),
    }


def with_leave_in(departure: dict[str, Any], now: datetime) -> dict[str, Any]:
    """The departure with whole minutes until leaving, rounded like the card shows them."""
    minutes = minutes_until(dt_util.parse_datetime(departure["leave_at"]), now)
    when = f"leave in {short_minutes(minutes)}" if minutes else "leave now"
    return {**departure, "leave_in": minutes, "summary": f"{departure['text']}, {when}"}


class Departures:
    """The next departures per route for its sensors, inside the route's own time windows.

    Every minute the sensors count down; the provider is only asked again every
    `every` minutes of the window that applies now, and not at all outside the windows.
    """

    def __init__(self, hass: HomeAssistant, store: AndiamoStore, timetable: Timetable) -> None:
        self.hass = hass
        self.store = store
        self.timetable = timetable
        # {route_id: departures as dicts, also the ones whose leave time passed}
        self.boards: dict[str, list[dict[str, Any]]] = {}
        self._fetched: dict[str, datetime] = {}
        # {route_id: the window that applies now}
        self._windows: dict[str, dict[str, Any]] = {}
        self._unsubs: list[CALLBACK_TYPE] = []
        self._task: asyncio.Task[None] | None = None

    def start(self) -> None:
        self._unsubs = [
            async_track_time_change(self.hass, self._tick, second=0),
            async_dispatcher_connect(self.hass, SIGNAL_DATA_CHANGED, self._data_changed),
        ]
        self._tick()

    def stop(self) -> None:
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()
        if self._task is not None:
            self._task.cancel()

    @callback
    def _data_changed(self) -> None:
        # A changed window, interval or lines applies at once.
        self._fetched.clear()
        self._windows.clear()
        self._tick()

    @callback
    def _tick(self, _now: datetime | None = None) -> None:
        if self._task is None or self._task.done():
            self._task = self.hass.async_create_background_task(
                self.async_update(), "andiamo_departures"
            )

    async def async_update(self) -> None:
        now = dt_util.now()
        wanted = {
            r["id"]: r
            for r in self.store.routes
            if r["mode"] == MODE_TRANSIT and r.get("departure_windows") and r.get("lines")
        }
        for route_id in set(self.boards) - set(wanted):
            self.boards.pop(route_id)
            self._fetched.pop(route_id, None)
            self._windows.pop(route_id, None)
        for route_id, route in wanted.items():
            window = active(route["departure_windows"], now)
            if window is None:
                self.boards.pop(route_id, None)
                self._fetched.pop(route_id, None)
                self._windows.pop(route_id, None)
                continue
            if window is not self._windows.get(route_id):
                # The next window may list more or update sooner: fetch at once.
                self._windows[route_id] = window
                self._fetched.pop(route_id, None)
            every = timedelta(minutes=window.get("every") or 1)
            fetched = self._fetched.get(route_id)
            if fetched is not None and now - fetched < every - SLACK:
                continue
            try:
                await self._fetch(route, every, self._count(route_id))
            except Exception as err:  # noqa: BLE001 - keep the last board; try again next minute
                _LOGGER.warning("Can't get departures for %s: %s", route["name"], err)
                continue
            self._fetched[route_id] = now
        async_dispatcher_send(self.hass, SIGNAL_BOARDS_CHANGED)

    def _count(self, route_id: str) -> int:
        return self._windows.get(route_id, {}).get("count") or 5

    async def _fetch(self, route: dict[str, Any], every: timedelta, count: int) -> None:
        station = self.store.route_station(route)
        walk = timedelta(minutes=station.get("walk_minutes", 0))
        keys = {line["key"] for line in route["lines"]}
        found = await self.timetable.departures(station["stop_ref"], every - SLACK)
        now = dt_util.utcnow()
        catchable = sorted(
            (d for d in found if d.line_key in keys and d.departure - walk >= now),
            key=lambda d: d.departure,
        )
        # More than listed, so the list stays full while the first ones are missed.
        self.boards[route["id"]] = [_departure(d, walk) for d in catchable[: count + 10]]

    def listed(self, route: dict[str, Any]) -> list[dict[str, Any]] | None:
        """The route's next departures with "leave in"; None outside its window."""
        board = self.boards.get(route["id"])
        if board is None:
            return None
        now = dt_util.utcnow()
        soon = now - timedelta(seconds=30)
        left = [d for d in board if dt_util.parse_datetime(d["leave_at"]) >= soon]
        return [with_leave_in(d, now) for d in left[: self._count(route["id"])]]
