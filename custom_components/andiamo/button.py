"""One button per public transport route (press to start, again to cancel) and one per car route (check the drive time now)."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import AndiamoConfigEntry
from .const import MODE_CAR, MODE_TRANSIT
from .entity import RouteEntity, setup_route_entities


async def async_setup_entry(
    hass: HomeAssistant,
    entry: AndiamoConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    setup_route_entities(
        hass,
        entry,
        async_add_entities,
        lambda route: route["mode"] == MODE_TRANSIT,
        RouteButton,
    )
    setup_route_entities(
        hass,
        entry,
        async_add_entities,
        lambda route: route["mode"] == MODE_CAR,
        CheckButton,
    )


class RouteButton(RouteEntity, ButtonEntity):
    key = "start"
    _attr_icon = "mdi:bus-clock"

    async def async_press(self) -> None:
        await self.runtime.runs.async_press(self.route_id)


class CheckButton(RouteEntity, ButtonEntity):
    key = "check"
    suffix = " check"
    _attr_icon = "mdi:car-clock"

    async def async_press(self) -> None:
        await self.runtime.runs.async_check_car(self.route_id)
