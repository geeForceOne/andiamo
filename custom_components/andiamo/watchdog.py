"""Watchdog: checks routes in their time window for traffic jams, delays and cancellations."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, time, timedelta
import logging
from typing import Any

from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect, async_dispatcher_send
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.util import dt as dt_util

from .const import (
    DEFAULT_PROBLEM_MINUTES,
    MODE_CAR,
    SIGNAL_DATA_CHANGED,
    SIGNAL_PROBLEMS_CHANGED,
    WATCH_INTERVAL,
)
from .providers import CarProvider, Departure, ProviderError, TransitProvider
from .store import AndiamoStore, DataError

_LOGGER = logging.getLogger(__name__)


def in_window(route: dict[str, Any], now: datetime) -> bool:
    """Whether `now` (local time) falls in the route's watch window.

    A window that ends before it starts runs past midnight and belongs to the
    day it started on.
    """
    days = route.get("watch_days") or []
    start, end = _time(route.get("watch_from")), _time(route.get("watch_to"))
    if not days or start is None or end is None:
        return False
    current = now.time().replace(second=0, microsecond=0)
    if start < end:
        return now.weekday() in days and start <= current < end
    if current >= start:
        return now.weekday() in days
    return current < end and (now - timedelta(days=1)).weekday() in days


def _time(value: str | None) -> time | None:
    try:
        return time.fromisoformat(value) if value else None
    except ValueError:
        return None


def _config(route: dict[str, Any]) -> tuple[Any, ...]:
    """What the watchdog depends on, to notice when a route changed."""
    return tuple(
        str(route.get(key))
        for key in (
            "mode", "origin_id", "destination_id", "station_id", "lines",
            "watch_days", "watch_from", "watch_to", "problem_minutes",
        )
    )


class Watchdog:
    """Checks every watched route every few minutes and keeps its problem, if any."""

    def __init__(
        self,
        hass: HomeAssistant,
        store: AndiamoStore,
        transit: Callable[[], TransitProvider],
        car: Callable[[], CarProvider],
    ) -> None:
        self.hass = hass
        self.store = store
        self.transit = transit
        self.car = car
        # {route_id: {"reason": "traffic" | "delayed" | "cancelled", "delay_minutes": n, ...}}
        self.problems: dict[str, dict[str, Any]] = {}
        self.watching: set[str] = set()
        self._configs: dict[str, tuple[Any, ...]] = {}
        self._unsubs: list[CALLBACK_TYPE] = []

    def start(self) -> None:
        self._unsubs = [
            async_track_time_interval(self.hass, self._tick, WATCH_INTERVAL),
            async_dispatcher_connect(self.hass, SIGNAL_DATA_CHANGED, self._data_changed),
        ]

    def stop(self) -> None:
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()

    @callback
    def _tick(self, _now: datetime) -> None:
        self.hass.async_create_task(self.async_check())

    @callback
    def _data_changed(self) -> None:
        """Check a route at once when its window or limit changed."""
        routes = {r["id"]: r for r in self.store.routes}
        changed = {rid for rid, r in routes.items() if self._configs.get(rid) != _config(r)}
        gone = set(self._configs) - set(routes)
        for route_id in gone:
            self._configs.pop(route_id)
            self.watching.discard(route_id)
            self.problems.pop(route_id, None)
        if changed:
            self.hass.async_create_task(self.async_check(changed))
        elif gone:
            async_dispatcher_send(self.hass, SIGNAL_PROBLEMS_CHANGED)

    async def async_check(self, route_ids: set[str] | None = None) -> None:
        before = (dict(self.problems), set(self.watching))
        now = dt_util.now()
        for route in list(self.store.routes):
            route_id = route["id"]
            if route_ids is not None and route_id not in route_ids:
                continue
            self._configs[route_id] = _config(route)
            if not in_window(route, now):
                self.watching.discard(route_id)
                self.problems.pop(route_id, None)
                continue
            self.watching.add(route_id)
            try:
                problem = await self._check(route)
            except (ProviderError, DataError) as err:
                # Keep what we knew; the next check tries again.
                _LOGGER.warning("Watchdog can't check %s: %s", route["name"], err)
                continue
            if problem:
                self.problems[route_id] = problem
            else:
                self.problems.pop(route_id, None)
        if (self.problems, self.watching) != before:
            async_dispatcher_send(self.hass, SIGNAL_PROBLEMS_CHANGED)

    async def _check(self, route: dict[str, Any]) -> dict[str, Any] | None:
        limit = route.get("problem_minutes") or DEFAULT_PROBLEM_MINUTES
        if route["mode"] == MODE_CAR:
            return await self._check_car(route, limit)
        return await self._check_transit(route, limit)

    async def _check_car(self, route: dict[str, Any], limit: int) -> dict[str, Any] | None:
        origin = self.store.location(route["origin_id"])
        destination = self.store.location(route["destination_id"])
        trip = await self.car().trip_now(
            (origin["latitude"], origin["longitude"]),
            (destination["latitude"], destination["longitude"]),
        )
        delay = round(trip.traffic_delay_seconds / 60)
        if delay < limit:
            return None
        return {
            "reason": "traffic",
            "delay_minutes": delay,
            "travel_minutes": round(trip.travel_seconds / 60),
        }

    async def _check_transit(self, route: dict[str, Any], limit: int) -> dict[str, Any] | None:
        """The next catchable departure of each ticked line; the first one cancelled or too late."""
        keys = {line["key"] for line in route.get("lines") or []}
        if not keys:
            return None
        station = self.store.route_station(route)
        walk = timedelta(minutes=station.get("walk_minutes", 0))
        found = await self.transit().departures(
            station["stop_ref"], dt_util.utcnow() + walk, include_cancelled=True
        )
        next_of_line: dict[str, Departure] = {}
        for departure in sorted(found, key=lambda d: d.planned_departure):
            if departure.line_key in keys:
                next_of_line.setdefault(departure.line_key, departure)
        for departure in sorted(next_of_line.values(), key=lambda d: d.planned_departure):
            delay = round(departure.delay.total_seconds() / 60)
            if departure.cancelled or delay >= limit:
                return {
                    "reason": "cancelled" if departure.cancelled else "delayed",
                    "delay_minutes": 0 if departure.cancelled else delay,
                    "line": departure.line,
                    "line_destination": departure.destination,
                    "departure": departure.planned_departure.isoformat(),
                    "station": station["name"],
                }
        return None

    def as_dict(self) -> dict[str, Any]:
        return {"problems": self.problems, "watching": sorted(self.watching)}
