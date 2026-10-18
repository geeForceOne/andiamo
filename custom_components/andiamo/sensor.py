"""One sensor per route: the leave time while a countdown runs."""

from __future__ import annotations

from datetime import date, datetime, time
from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from . import AndiamoConfigEntry
from .const import MODE_CAR, SIGNAL_RUNS_CHANGED
from .entity import RouteEntity, setup_route_entities
from .runner import arrival
from .store import DataError


async def async_setup_entry(
    hass: HomeAssistant,
    entry: AndiamoConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    setup_route_entities(hass, entry, async_add_entities, lambda _: True, LeaveSensor)


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
        return {k: v for k, v in run.items() if k not in ("route_id", "leave_at")}
