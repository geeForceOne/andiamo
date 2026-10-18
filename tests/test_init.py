"""Setup, websocket commands and entities, end to end."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.andiamo.const import CONF_OJP_KEY, CONF_TOMTOM_KEY, DOMAIN
from custom_components.andiamo.providers import Departure

from .test_runner import START, at


@pytest.fixture
async def ws(hass: HomeAssistant, hass_ws_client, transit, car, freezer):
    """Andiamo set up with fake providers; the frontend parts are stubbed."""
    await hass.config.async_set_time_zone("Europe/Zurich")
    client = await hass_ws_client(hass)
    # After signing in, or the test client's token would be expired.
    freezer.move_to(START)
    entry = MockConfigEntry(
        domain=DOMAIN, data={CONF_OJP_KEY: "ojp", CONF_TOMTOM_KEY: "tomtom"}
    )
    entry.add_to_hass(hass)
    with (
        patch("custom_components.andiamo.panel_custom.async_register_panel") as panel,
        patch("custom_components.andiamo.frontend.add_extra_js_url"),
        patch("custom_components.andiamo.frontend.async_remove_panel"),
        patch.object(hass.http, "async_register_static_paths", AsyncMock()),
        patch("custom_components.andiamo.AndiamoRuntime.transit", return_value=transit),
        patch("custom_components.andiamo.AndiamoRuntime.car", return_value=car),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        assert entry.state is ConfigEntryState.LOADED
        assert panel.call_args.kwargs["frontend_url_path"] == "andiamo"

        yield Client(client)
        await hass.config_entries.async_unload(entry.entry_id)


class Client:
    """Sends commands; states pushed by the subscription are kept in `events`."""

    def __init__(self, client) -> None:
        self._client = client
        self._id = 1000
        self.events: list[dict] = []

    async def __call__(self, type_: str, **data) -> dict:
        self._id += 1
        await self._client.send_json({"id": self._id, "type": f"andiamo/{type_}", **data})
        while True:
            msg = await self._client.receive_json(timeout=5)
            if msg["type"] == "event":
                self.events.append(msg["event"])
            elif msg["id"] == self._id:
                return msg

    async def state(self) -> dict:
        """Subscribe and return the first state."""
        assert (await self("subscribe"))["success"]
        if not self.events:
            msg = await self._client.receive_json(timeout=5)
            self.events.append(msg["event"])
        return self.events[-1]


async def test_panel_flow(hass: HomeAssistant, ws, transit) -> None:
    first = await ws.state()
    home = first["locations"][0]
    assert home["main"] is True
    assert first["providers"] == {"transit": True, "car": True}

    work = await ws("location/save", item={"name": "Work", "latitude": 47.4, "longitude": 8.5})
    assert work["success"], work
    work = work["result"]
    assert ws.events[-1]["locations"][-1]["name"] == "Work"

    stops = await ws("search_stops", query="Zürich")
    assert stops["result"][0]["name"] == "Zürich"

    station = await ws(
        "station/save",
        item={"location_id": home["id"], "name": "Tram", "stop_ref": "x", "walk_minutes": 5},
    )
    assert station["result"]["main"] is True

    route = await ws(
        "route/save",
        item={"name": "Work", "mode": "transit", "origin_id": home["id"], "lines": [{"key": "10|Flughafen", "name": "10", "destination": "Flughafen"}]},
    )
    route = route["result"]
    await hass.async_block_till_done()

    registry = er.async_get(hass)
    button = registry.async_get_entity_id("button", DOMAIN, f"{route['id']}_start")
    sensor = registry.async_get_entity_id("sensor", DOMAIN, f"{route['id']}_leave")
    assert button and sensor
    assert hass.states.get(sensor).state == "unknown"

    transit.result = [
        Departure(
            departure=at(12),
            planned_departure=at(12),
            line="10",
            destination="Flughafen",
            mode="tram",
            line_key="10|Flughafen",
        )
    ]
    await hass.services.async_call("button", "press", {"entity_id": button}, blocking=True)
    await hass.async_block_till_done()
    assert dt_util.parse_datetime(hass.states.get(sensor).state) == at(7)
    assert hass.states.get(sensor).attributes["line"] == "10"

    # Pressing again cancels.
    await hass.services.async_call("button", "press", {"entity_id": button}, blocking=True)
    await hass.async_block_till_done()
    assert hass.states.get(sensor).state == "unknown"

    # Renaming follows; deleting removes the entities.
    await ws("route/save", item={**route, "name": "Office"})
    await hass.async_block_till_done()
    assert hass.states.get(button).name == "Andiamo Office"

    assert (await ws("route/delete", item_id=route["id"]))["success"]
    await hass.async_block_till_done()
    assert registry.async_get(button) is None
    assert registry.async_get(sensor) is None


async def test_errors_are_reported(hass: HomeAssistant, ws) -> None:
    home = (await ws.state())["locations"][0]["id"]
    result = await ws(
        "route/save",
        item={"name": "Loop", "mode": "car", "origin_id": home, "destination_id": home},
    )
    assert not result["success"]
    assert result["error"]["message"] == "Start and destination are the same"


async def test_start_car_from_card(hass: HomeAssistant, ws, car) -> None:
    home = (await ws.state())["locations"][0]["id"]
    gf = (await ws("location/save", item={"name": "GF", "latitude": 47.2, "longitude": 8.3}))["result"]
    route = (await ws(
        "route/save", item={"name": "GF", "mode": "car", "origin_id": home, "destination_id": gf["id"]}
    ))["result"]

    car.departure = at(80)
    # Local time without zone, as a browser may send it: 12:00 in Zurich.
    result = await ws("start_car", route_id=route["id"], arrive_at="2026-10-19T12:00:00")
    assert result["success"], result
    runtime = hass.data[DOMAIN]
    assert runtime.runs.runs[route["id"]].arrive_at == at(120)

    assert (await ws("cancel", route_id=route["id"]))["success"]
    assert runtime.runs.runs == {}
