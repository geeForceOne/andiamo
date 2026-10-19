"""One problem sensor per route: on while the watchdog sees a jam, delay or cancellation."""

from __future__ import annotations

from typing import Any

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import AndiamoConfigEntry
from .const import SIGNAL_PROBLEMS_CHANGED
from .entity import RouteEntity, setup_route_entities


async def async_setup_entry(
    hass: HomeAssistant,
    entry: AndiamoConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    setup_route_entities(hass, entry, async_add_entities, lambda _: True, ProblemSensor)


class ProblemSensor(RouteEntity, BinarySensorEntity):
    key = "problem"
    suffix = " problem"
    _attr_device_class = BinarySensorDeviceClass.PROBLEM

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(
            async_dispatcher_connect(self.hass, SIGNAL_PROBLEMS_CHANGED, self.async_write_ha_state)
        )

    @property
    def is_on(self) -> bool:
        return self.route_id in self.runtime.watchdog.problems

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "watching": self.route_id in self.runtime.watchdog.watching,
            "problem_minutes": self.route.get("problem_minutes"),
            **self.runtime.watchdog.problems.get(self.route_id, {}),
        }
