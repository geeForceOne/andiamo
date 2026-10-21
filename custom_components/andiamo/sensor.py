"""One sensor per route with the leave time while a countdown runs, and one per car route with its drive time."""

from __future__ import annotations

from datetime import date, datetime, time
from typing import Any

from homeassistant.components.sensor import RestoreSensor, SensorDeviceClass, SensorEntity
from homeassistant.const import UnitOfTime
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from . import AndiamoConfigEntry
from .const import MODE_CAR, MODE_TRANSIT, SIGNAL_BOARDS_CHANGED, SIGNAL_RUNS_CHANGED
from .entity import RouteEntity, setup_route_entities
from .runner import arrival
from .store import DataError


async def async_setup_entry(
    hass: HomeAssistant,
    entry: AndiamoConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    setup_route_entities(hass, entry, async_add_entities, lambda _: True, LeaveSensor)
    setup_route_entities(
        hass, entry, async_add_entities, lambda route: route["mode"] == MODE_CAR, DriveTimeSensor
    )
    # Departure sensors only for routes that have a window for them.
    for sensor in (NextDepartureSensor, DeparturesSensor):
        setup_route_entities(
            hass,
            entry,
            async_add_entities,
            lambda route: route["mode"] == MODE_TRANSIT and bool(route.get("departure_windows")),
            sensor,
        )


class LeaveSensor(RouteEntity, SensorEntity):
    key = "leave"
    _attr_device_class = SensorDeviceClass.TIMESTAMP

    @property
    def icon(self) -> str:
        return "mdi:car-clock" if self.route["mode"] == MODE_CAR else "mdi:bus-clock"

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(
            async_dispatcher_connect(self.hass, SIGNAL_RUNS_CHANGED, self._runs_changed)
        )

    async def async_start_route(
        self, time: time | None = None, date: date | None = None, speaker: str | None = None
    ) -> None:
        """The andiamo.start action."""
        if date is not None and time is None:
            raise DataError("Set a time with the date")
        arrive_at = arrival(time, date) if time is not None else None
        await self.runtime.runs.async_start(self.route_id, arrive_at, speaker)

    async def async_check_route(self, speaker: str | None = None) -> dict[str, Any]:
        """The andiamo.check action: a car route's drive time right now."""
        return await self.runtime.runs.async_check_car(self.route_id, speaker)

    async def async_stop_route(self) -> None:
        """The andiamo.stop action; nothing happens when the route isn't running."""
        await self.runtime.runs.async_cancel(self.route_id)

    @callback
    def _runs_changed(self) -> None:
        self.async_write_ha_state()

    def _run(self) -> dict[str, Any] | None:
        run = self.runtime.runs.runs.get(self.route_id)
        return run.as_dict() if run else None

    @property
    def native_value(self) -> datetime | None:
        run = self._run()
        if run and run["leave_at"]:
            return dt_util.parse_datetime(run["leave_at"])
        return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        run = self._run() or {}
        attributes = {k: v for k, v in run.items() if k not in ("route_id", "leave_at")}
        # The last announcement stays after the run, so a display can show "go now".
        return {**attributes, **self.runtime.runs.messages.get(self.route_id, {})}


class DriveTimeSensor(RouteEntity, RestoreSensor):
    """Minutes by car right now, from the last "check now"; kept over a restart."""

    key = "drive_time"
    suffix = " drive time"
    _attr_icon = "mdi:car-clock"
    _attr_device_class = SensorDeviceClass.DURATION
    _attr_native_unit_of_measurement = UnitOfTime.MINUTES

    def __init__(self, runtime, route) -> None:
        super().__init__(runtime, route)
        self._check: dict[str, Any] = {}

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        if (last := await self.async_get_last_state()) is not None and last.state.isdigit():
            self._check = {"travel_minutes": int(last.state), **last.attributes}
        self.async_on_remove(
            async_dispatcher_connect(self.hass, SIGNAL_RUNS_CHANGED, self._runs_changed)
        )

    @callback
    def _runs_changed(self) -> None:
        check = self.runtime.runs.checks.get(self.route_id)
        if check is not None and check is not self._check:
            self._check = check
            self.async_write_ha_state()

    @property
    def native_value(self) -> int | None:
        return self._check.get("travel_minutes")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            key: self._check[key]
            for key in ("traffic_minutes", "length_km", "message", "checked_at")
            if key in self._check
        }


class _DepartureSensor(RouteEntity, SensorEntity):
    """Follows the route's departure board, which updates every minute in its window."""

    _attr_icon = "mdi:bus-clock"

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(
            async_dispatcher_connect(self.hass, SIGNAL_BOARDS_CHANGED, self.async_write_ha_state)
        )

    def _listed(self) -> list[dict[str, Any]] | None:
        return self.runtime.departures.listed(self.route)


class NextDepartureSensor(_DepartureSensor):
    """The next departure one can catch, as a short text for a display."""

    key = "next_departure"
    suffix = " next departure"

    def _next(self) -> dict[str, Any] | None:
        # Skip cancelled ones: the one to take is what matters here.
        return next((d for d in self._listed() or [] if not d["cancelled"]), None)

    @property
    def native_value(self) -> str | None:
        found = self._next()
        return found["summary"] if found else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        found = self._next()
        if not found:
            return {}
        return {
            key: found[key]
            for key in (
                "line", "destination", "departure", "delay_minutes", "cancelled",
                "leave_at", "leave_in", "text",
            )
        }


class DeparturesSensor(_DepartureSensor):
    """How many departures are listed, with the list in `departures`."""

    key = "departures"
    suffix = " departures"
    # The list changes every minute; keep it out of the history database.
    _unrecorded_attributes = frozenset({"departures"})

    @property
    def native_value(self) -> int | None:
        listed = self._listed()
        return None if listed is None else len(listed)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {"departures": self._listed() or []}
