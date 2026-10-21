"""Stored places, stations, routes and settings."""

from __future__ import annotations

from typing import Any
import uuid

from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.storage import Store

from . import windows
from .const import (
    ANNOUNCE_NOTIFICATION,
    ANNOUNCE_SPEAKER,
    DEFAULT_CAR_LEAD_MINUTES,
    DEFAULT_LIMIT_OJP,
    DEFAULT_LIMIT_TOMTOM,
    DEFAULT_LANGUAGE,
    MODE_CAR,
    MODE_TRANSIT,
    SIGNAL_DATA_CHANGED,
    STORAGE_KEY,
    STORAGE_VERSION,
)

DEFAULT_SETTINGS: dict[str, Any] = {
    "tts_entity": None,
    "speaker": None,
    "language": DEFAULT_LANGUAGE,
    "car_lead_minutes": DEFAULT_CAR_LEAD_MINUTES,
    "announce": ANNOUNCE_SPEAKER,
    "templates": {},
    # {"de": {"go_now": "Ab jetzt!"}}: only the messages the user replaced.
    "limit_tomtom": DEFAULT_LIMIT_TOMTOM,
    "limit_ojp": DEFAULT_LIMIT_OJP,
}


class DataError(HomeAssistantError):
    """A change the stored data can't take, with a message for the user."""


class AndiamoStore:
    """Everything the user configures in the panel, kept in HA's storage.

    Locations are places (Home, Work, Girlfriend). Stations belong to a
    location and store the walking time to them. A public transport route
    boards at a station of its start and takes the lines ticked for it; a car
    route goes from one location to another. One location is the main one,
    and each location has one main station.
    """

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass
        self._store: Store[dict[str, Any]] = Store(hass, STORAGE_VERSION, STORAGE_KEY)
        self.settings: dict[str, Any] = dict(DEFAULT_SETTINGS)
        self.locations: list[dict[str, Any]] = []
        self.stations: list[dict[str, Any]] = []
        self.routes: list[dict[str, Any]] = []
        # Car countdowns that were set up and must survive a restart:
        # {route_id: {"arrive_at": iso, "speaker": entity or None}}.
        self.car_runs: dict[str, dict[str, Any]] = {}
        # The last car trip planned per route, to show the drive time.
        self.trips: dict[str, dict[str, int]] = {}
        # API calls made today (UTC): {"day": "2026-10-20", "tomtom": 12, "ojp": 340}.
        self.usage: dict[str, Any] = {}

    async def async_load(self) -> None:
        data = await self._store.async_load()
        if data:
            self.settings = _clean_settings(data.get("settings", {}))
            self.locations = data.get("locations", [])
            self.stations = data.get("stations", [])
            self.routes = [_clean_route(r) for r in data.get("routes", [])]
            self.car_runs = {
                route_id: run if isinstance(run, dict) else {"arrive_at": run}
                for route_id, run in data.get("car_runs", {}).items()
            }
            self.trips = data.get("trips", {})
            self.usage = data.get("usage", {})
        if not self.locations:
            # The main location starts out as HA's home.
            self.locations.append(
                {
                    "id": _new_id(),
                    "name": self.hass.config.location_name or "Home",
                    "latitude": self.hass.config.latitude,
                    "longitude": self.hass.config.longitude,
                    "main": True,
                }
            )
            await self.async_save()

    @callback
    def delay_save(self) -> None:
        """Save a little later, e.g. after counting an API call."""
        self._store.async_delay_save(lambda: self.as_dict(include_runs=True), 30)

    async def async_save(self, notify: bool = True) -> None:
        await self._store.async_save(self.as_dict(include_runs=True))
        if notify:
            async_dispatcher_send(self.hass, SIGNAL_DATA_CHANGED)

    def as_dict(self, include_runs: bool = False) -> dict[str, Any]:
        data: dict[str, Any] = {
            "settings": self.settings,
            "locations": self.locations,
            "stations": self.stations,
            "routes": self.routes,
            "trips": self.trips,
        }
        if include_runs:
            data["car_runs"] = self.car_runs
            data["usage"] = self.usage
        return data

    # Lookups

    def location(self, location_id: str) -> dict[str, Any]:
        return _find(self.locations, location_id, "Location")

    def station(self, station_id: str) -> dict[str, Any]:
        return _find(self.stations, station_id, "Station")

    def route(self, route_id: str) -> dict[str, Any]:
        return _find(self.routes, route_id, "Route")

    def main_station(self, location_id: str) -> dict[str, Any] | None:
        stations = [s for s in self.stations if s["location_id"] == location_id]
        return next((s for s in stations if s["main"]), stations[0] if stations else None)

    def route_station(self, route: dict[str, Any]) -> dict[str, Any]:
        """The station a public transport route boards at."""
        if route.get("station_id"):
            return self.station(route["station_id"])
        station = self.main_station(route["origin_id"])
        if station is None:
            location = self.location(route["origin_id"])
            raise DataError(f"{location['name']} has no station yet")
        return station

    # Changes

    async def async_update_settings(self, changes: dict[str, Any]) -> None:
        self.settings.update(changes)
        await self.async_save()

    async def async_save_location(self, item: dict[str, Any]) -> dict[str, Any]:
        location = _upsert(self.locations, item)
        _keep_one_main(self.locations, location)
        await self.async_save()
        return location

    async def async_delete_location(self, location_id: str) -> None:
        location = self.location(location_id)
        used = [
            r["name"]
            for r in self.routes
            if location_id in (r["origin_id"], r.get("destination_id"))
        ]
        if used:
            raise DataError(f"{location['name']} is used by: {', '.join(used)}")
        self.locations.remove(location)
        self.stations = [s for s in self.stations if s["location_id"] != location_id]
        _keep_one_main(self.locations)
        await self.async_save()

    async def async_save_station(self, item: dict[str, Any]) -> dict[str, Any]:
        self.location(item["location_id"])
        station = _upsert(self.stations, item)
        _keep_one_main(self._stations_of(station["location_id"]), station)
        await self.async_save()
        return station

    async def async_delete_station(self, station_id: str) -> None:
        station = self.station(station_id)
        used = [r["name"] for r in self.routes if r.get("station_id") == station_id]
        if used:
            raise DataError(f"{station['name']} is used by: {', '.join(used)}")
        self.stations.remove(station)
        _keep_one_main(self._stations_of(station["location_id"]))
        await self.async_save()

    async def async_save_route(self, item: dict[str, Any]) -> dict[str, Any]:
        self.location(item["origin_id"])
        if item["mode"] == MODE_TRANSIT:
            if not item.get("lines"):
                raise DataError("Pick at least one line")
            if item.get("station_id"):
                station = self.station(item["station_id"])
                if station["location_id"] != item["origin_id"]:
                    raise DataError(f"{station['name']} doesn't belong to the start")
            item = {**item, "destination_id": None}
        elif item["mode"] == MODE_CAR:
            if not item.get("destination_id"):
                raise DataError("Pick a destination")
            self.location(item["destination_id"])
            if item["origin_id"] == item["destination_id"]:
                raise DataError("Start and destination are the same")
            # Departure sensors are for public transport only.
            item = {**item, "station_id": None, "lines": [], "departure_windows": []}
            old = self._old_route(item)
            if (old.get("origin_id"), old.get("destination_id")) != (
                item["origin_id"],
                item["destination_id"],
            ):
                # Another trip now; the last drive time no longer fits.
                self.trips.pop(item.get("id"), None)
        else:
            raise DataError(f"Unknown mode {item['mode']}")
        try:
            windows.check(item.get("watch_windows") or [], "watch")
            windows.check(item.get("departure_windows") or [], "departure sensor")
        except ValueError as err:
            raise DataError(str(err)) from err
        route = _upsert(self.routes, item, has_main=False)
        await self.async_save()
        return route

    async def async_delete_route(self, route_id: str) -> None:
        self.routes.remove(self.route(route_id))
        self.car_runs.pop(route_id, None)
        self.trips.pop(route_id, None)
        await self.async_save()

    def _old_route(self, item: dict[str, Any]) -> dict[str, Any]:
        return next((r for r in self.routes if r["id"] == item.get("id")), {})

    def _stations_of(self, location_id: str) -> list[dict[str, Any]]:
        return [s for s in self.stations if s["location_id"] == location_id]


def _clean_settings(saved: dict[str, Any]) -> dict[str, Any]:
    """Test mode became "Announce on: Notification"."""
    settings = {**DEFAULT_SETTINGS, **saved}
    if "announce" not in saved and settings.pop("test_mode", False):
        settings["announce"] = ANNOUNCE_NOTIFICATION
    settings.pop("test_mode", None)
    return settings


def _clean_route(route: dict[str, Any]) -> dict[str, Any]:
    """Drop the buffer older versions stored; fill in fields added since; one window became a list."""
    route = {k: v for k, v in route.items() if k != "buffer_minutes"}
    route.setdefault("lines", [])
    route.setdefault("speaker", None)
    route.setdefault("announce", None)
    if "watch_windows" not in route:
        route["watch_windows"] = windows.migrate(
            route, "watch", {"problem_minutes": "problem_minutes"}
        )
    if "departure_windows" not in route:
        route["departure_windows"] = windows.migrate(
            route, "departures", {"departures_every": "every", "departures_count": "count"}
        )
    if route["mode"] == MODE_TRANSIT:
        # The ticked lines replaced the destination; until some are picked
        # the route can't start.
        route["destination_id"] = None
    return route


def _new_id() -> str:
    return uuid.uuid4().hex[:12]


def _find(items: list[dict[str, Any]], item_id: str, kind: str) -> dict[str, Any]:
    for item in items:
        if item["id"] == item_id:
            return item
    raise DataError(f"{kind} {item_id} not found")


def _upsert(
    items: list[dict[str, Any]], item: dict[str, Any], has_main: bool = True
) -> dict[str, Any]:
    item = dict(item)
    if item.get("id"):
        existing = _find(items, item["id"], "Item")
        existing.update(item)
        return existing
    item["id"] = _new_id()
    if has_main:
        item.setdefault("main", False)
    items.append(item)
    return item


def _keep_one_main(
    items: list[dict[str, Any]], changed: dict[str, Any] | None = None
) -> None:
    """Exactly one item is main: the one just made main, else the first."""
    if changed is not None and changed.get("main"):
        for item in items:
            item["main"] = item is changed
    if items and not any(item.get("main") for item in items):
        items[0]["main"] = True
