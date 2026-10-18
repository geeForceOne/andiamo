"""Entities that follow the stored routes as they are added, renamed or removed."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import SIGNAL_DATA_CHANGED

if TYPE_CHECKING:
    from . import AndiamoConfigEntry, AndiamoRuntime


class RouteEntity(Entity):
    """An entity for one route, named after it."""

    _attr_should_poll = False
    key: str

    def __init__(self, runtime: AndiamoRuntime, route: dict[str, Any]) -> None:
        self.runtime = runtime
        self.route_id = route["id"]
        self._attr_unique_id = f"{route['id']}_{self.key}"
        self._attr_name = f"Andiamo {route['name']}"

    @property
    def route(self) -> dict[str, Any]:
        return self.runtime.store.route(self.route_id)

    @callback
    def route_changed(self) -> None:
        self._attr_name = f"Andiamo {self.route['name']}"
        self.async_write_ha_state()


def setup_route_entities(
    hass: HomeAssistant,
    entry: AndiamoConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
    wanted: Callable[[dict[str, Any]], bool],
    create: Callable[[AndiamoRuntime, dict[str, Any]], RouteEntity],
) -> None:
    runtime = entry.runtime_data
    entities: dict[str, RouteEntity] = {}

    @callback
    def sync() -> None:
        routes = {r["id"]: r for r in runtime.store.routes if wanted(r)}
        new = [create(runtime, r) for rid, r in routes.items() if rid not in entities]
        for entity in new:
            entities[entity.route_id] = entity
        if new:
            async_add_entities(new)
        registry = er.async_get(hass)
        for route_id in [rid for rid in entities if rid not in routes]:
            entity = entities.pop(route_id)
            if entity.entity_id and registry.async_get(entity.entity_id):
                registry.async_remove(entity.entity_id)
        for route_id, entity in entities.items():
            if entity.hass and entity.name != f"Andiamo {routes[route_id]['name']}":
                entity.route_changed()

    sync()
    entry.async_on_unload(async_dispatcher_connect(hass, SIGNAL_DATA_CHANGED, sync))

