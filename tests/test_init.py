"""Setup, websocket commands and entities, end to end."""

from __future__ import annotations

from datetime import date, datetime
import re
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp

import pytest

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util

from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed

from custom_components.andiamo.const import CONF_OJP_KEY, CONF_TOMTOM_KEY, DOMAIN
from custom_components.andiamo.providers import Departure
from custom_components.andiamo.providers.ojp import OjpProvider
from custom_components.andiamo.providers.tomtom import TomTomProvider

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
        # A fingerprint of the file, so browsers load every changed version.
        assert re.fullmatch(r"/andiamo_static/andiamo-panel\.js\?v=[0-9a-f]{12}", panel.call_args.kwargs["module_url"])

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

    async def event(self, key: str) -> dict:
        """The next pushed event that has `key`, e.g. a timetable's "boards"."""
        while True:
            for event in self.events:
                if key in event:
                    self.events.remove(event)
                    return event
            msg = await self._client.receive_json(timeout=5)
            if msg["type"] == "event":
                self.events.append(msg["event"])

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
    result = await ws("start", route_id=route["id"], arrive_at="2026-10-19T12:00:00")
    assert result["success"], result
    runtime = hass.data[DOMAIN]
    assert runtime.runs.runs[route["id"]].arrive_at == at(120)

    assert (await ws("cancel", route_id=route["id"]))["success"]
    assert runtime.runs.runs == {}


async def test_message_templates(hass: HomeAssistant, ws) -> None:
    state = await ws.state()
    assert state["messages"]["de"]["go_now"] == "Los jetzt!"

    ok = await ws("settings", changes={"templates": {"de": {"go_now": "Ab, {route}!"}}})
    assert ok["success"], ok
    typo = await ws("settings", changes={"templates": {"de": {"go_now": "Ab um {tme}!"}}})
    assert not typo["success"]
    assert "tme" in typo["error"]["message"]


async def test_start_and_stop_actions(hass: HomeAssistant, ws, car, transit) -> None:
    home = (await ws.state())["locations"][0]["id"]
    gf = (await ws("location/save", item={"name": "GF", "latitude": 47.2, "longitude": 8.3}))["result"]
    route = (await ws(
        "route/save", item={"name": "GF", "mode": "car", "origin_id": home, "destination_id": gf["id"]}
    ))["result"]
    await hass.async_block_till_done()
    sensor = er.async_get(hass).async_get_entity_id("sensor", DOMAIN, f"{route['id']}_leave")
    runtime = hass.data[DOMAIN]

    car.departure = at(80)
    await hass.services.async_call(
        DOMAIN,
        "start",
        {"time": "12:00", "date": "2026-10-19", "speaker": "media_player.kitchen"},
        target={"entity_id": sensor},
        blocking=True,
    )
    run = runtime.runs.runs[route["id"]]
    assert run.arrive_at == at(120)
    assert run.speaker == "media_player.kitchen"
    assert runtime.store.car_runs[route["id"]]["speaker"] == "media_player.kitchen"
    # The drive time stays for the route list.
    assert (await ws.state())["trips"][route["id"]] == {
        "travel_minutes": 41, "traffic_minutes": 3, "length_km": 32.4
    }

    await hass.services.async_call(DOMAIN, "stop", target={"entity_id": sensor}, blocking=True)
    assert runtime.runs.runs == {}
    # Stopping a route that isn't running is fine.
    await hass.services.async_call(DOMAIN, "stop", target={"entity_id": sensor}, blocking=True)

    with pytest.raises(HomeAssistantError, match="set an arrival time"):
        await hass.services.async_call(
            DOMAIN, "start", target={"entity_id": sensor}, blocking=True
        )


async def test_start_action_time_is_for_cars(hass: HomeAssistant, ws, transit) -> None:
    home = (await ws.state())["locations"][0]["id"]
    await ws(
        "station/save",
        item={"location_id": home, "name": "Tram", "stop_ref": "ch:1:sloid:1", "walk_minutes": 5},
    )
    route = (await ws("route/save", item={
        "name": "Work", "mode": "transit", "origin_id": home,
        "lines": [{"key": "10|Flughafen", "name": "10", "destination": "Flughafen"}],
    }))["result"]
    await hass.async_block_till_done()
    sensor = er.async_get(hass).async_get_entity_id("sensor", DOMAIN, f"{route['id']}_leave")

    with pytest.raises(HomeAssistantError, match="Time only works for car routes"):
        await hass.services.async_call(
            DOMAIN, "start", {"time": "12:00"}, target={"entity_id": sensor}, blocking=True
        )


async def test_watchdog_problem_sensor(hass: HomeAssistant, ws, car) -> None:
    home = (await ws.state())["locations"][0]["id"]
    gf = (await ws("location/save", item={"name": "GF", "latitude": 47.2, "longitude": 8.3}))["result"]
    car.now = (3000, 20 * 60)
    # Monday 10:00 in Zurich is inside 9:00–11:00.
    route = (await ws(
        "route/save",
        item={
            "name": "GF", "mode": "car", "origin_id": home, "destination_id": gf["id"],
            "watch_windows": [{"days": [0], "from": "9:00", "to": "11:00", "problem_minutes": 15}],
        },
    ))["result"]
    assert route["watch_windows"][0]["from"] == "09:00"
    await hass.async_block_till_done()

    entity_id = er.async_get(hass).async_get_entity_id("binary_sensor", DOMAIN, f"{route['id']}_problem")
    state = hass.states.get(entity_id)
    assert state.state == "on"
    assert state.name == "Andiamo GF problem"
    assert state.attributes["reason"] == "traffic"
    assert state.attributes["delay_minutes"] == 20
    assert state.attributes["problem_minutes"] == 15
    assert (await ws.state())["problems"][route["id"]]["reason"] == "traffic"

    # Overlapping windows are refused.
    bad = await ws("route/save", item={**route, "watch_windows": [
        *route["watch_windows"], {"days": [0, 1], "from": "10:30", "to": "12:00"},
    ]})
    assert bad["error"]["message"] == "Watch windows overlap on Mon 10:30–11:00"

    # A second window with its own limit; Monday 10:00 is still in the first one.
    route = (await ws("route/save", item={**route, "watch_windows": [
        {"days": [5, 6], "from": "08:00", "to": "12:00", "problem_minutes": 30},
        *route["watch_windows"],
    ]}))["result"]
    await hass.async_block_till_done()
    assert hass.states.get(entity_id).state == "on"
    assert hass.states.get(entity_id).attributes["problem_minutes"] == 15

    # Watching switched off: the problem goes with it.
    await ws("route/save", item={**route, "watch_windows": []})
    await hass.async_block_till_done()
    assert hass.states.get(entity_id).state == "off"


async def test_announce_setting_and_message_attribute(hass: HomeAssistant, ws, transit) -> None:
    assert (await ws("settings", changes={"announce": "off"}))["success"]
    assert not (await ws("settings", changes={"announce": "loud"}))["success"]
    home = (await ws.state())["locations"][0]["id"]
    station = (await ws(
        "station/save", item={"location_id": home, "name": "Tram", "stop_ref": "x", "walk_minutes": 5}
    ))["result"]
    line = {"key": "10|Flughafen", "name": "10", "destination": "Flughafen"}
    route = (await ws(
        "route/save", item={"name": "Tram", "mode": "transit", "origin_id": home, "lines": [line]}
    ))["result"]
    await hass.async_block_till_done()
    transit.result = [
        Departure(at(12), at(12), "10", "Flughafen", "tram", "10|Flughafen"),
    ]

    assert (await ws("start", route_id=route["id"]))["success"]
    await hass.async_block_till_done()
    sensor = er.async_get(hass).async_get_entity_id("sensor", DOMAIN, f"{route['id']}_leave")
    assert hass.states.get(sensor).attributes["message"].startswith("Du musst um 10:07 los")
    assert not hass.states.async_all("persistent_notification")


async def _car_route(ws, hass) -> dict:
    home = (await ws.state())["locations"][0]["id"]
    gf = (await ws("location/save", item={"name": "GF", "latitude": 47.2, "longitude": 8.3}))["result"]
    route = (await ws(
        "route/save", item={"name": "GF", "mode": "car", "origin_id": home, "destination_id": gf["id"]}
    ))["result"]
    await hass.async_block_till_done()
    return route


async def test_check_car_now(hass: HomeAssistant, ws, car) -> None:
    route = await _car_route(ws, hass)
    registry = er.async_get(hass)
    leave = registry.async_get_entity_id("sensor", DOMAIN, f"{route['id']}_leave")
    drive = registry.async_get_entity_id("sensor", DOMAIN, f"{route['id']}_drive_time")
    button = registry.async_get_entity_id("button", DOMAIN, f"{route['id']}_check")
    assert hass.states.get(drive).state == "unknown"
    assert hass.states.get(button).name == "Andiamo GF check"

    # From the panel or card: the result comes back, the route list shows it.
    car.now = (1500, 360)
    say = AsyncMock()
    patch.object(hass.data[DOMAIN].runs.announcer, "async_say", say).start()
    result = await ws("check", route_id=route["id"])
    assert result["success"], result
    assert result["result"]["travel_minutes"] == 25
    assert result["result"]["message"] == "Bis GF brauchst du jetzt 25 Minuten, davon 6 Minuten Stau."
    assert (await ws.state())["trips"][route["id"]] == {
        "travel_minutes": 25, "traffic_minutes": 6, "length_km": 32.4
    }
    await hass.async_block_till_done()
    state = hass.states.get(drive)
    assert state.state == "25"
    assert state.attributes["unit_of_measurement"] == "min"
    assert state.attributes["traffic_minutes"] == 6
    assert state.attributes["message"].startswith("Bis GF")
    # Said, since announcements go to the speaker.
    assert say.call_args.args[0] == result["result"]["message"]
    assert say.call_args.args[3] == "speaker"

    # The action answers automations; with announcements as notifications it stays quiet.
    assert (await ws("settings", changes={"announce": "notification", "language": "en"}))["success"]
    car.now = (1200, 0)
    response = await hass.services.async_call(
        DOMAIN, "check", target={"entity_id": leave}, blocking=True, return_response=True
    )
    assert response[leave]["travel_minutes"] == 20
    assert response[leave]["message"] == "Driving to GF takes 20 minutes right now, no traffic."
    await hass.async_block_till_done()
    assert hass.states.get(drive).state == "20"
    assert say.call_count == 1

    car.now = (600, 0)
    await hass.services.async_call("button", "press", {"entity_id": button}, blocking=True)
    await hass.async_block_till_done()
    assert hass.states.get(drive).state == "10"


async def test_check_is_for_cars(hass: HomeAssistant, ws, transit) -> None:
    home = (await ws.state())["locations"][0]["id"]
    await ws("station/save", item={"location_id": home, "name": "Tram", "stop_ref": "x", "walk_minutes": 5})
    route = (await ws("route/save", item={
        "name": "Work", "mode": "transit", "origin_id": home,
        "lines": [{"key": "10|Flughafen", "name": "10", "destination": "Flughafen"}],
    }))["result"]
    result = await ws("check", route_id=route["id"])
    assert result["error"]["message"] == "Work is not a car route"


async def test_start_from_card_starts_over(hass: HomeAssistant, ws, transit) -> None:
    home = (await ws.state())["locations"][0]["id"]
    await ws("station/save", item={"location_id": home, "name": "Tram", "stop_ref": "x", "walk_minutes": 5})
    route = (await ws("route/save", item={
        "name": "Work", "mode": "transit", "origin_id": home,
        "lines": [{"key": "10|Flughafen", "name": "10", "destination": "Flughafen"}],
    }))["result"]
    transit.result = [Departure(at(12), at(12), "10", "Flughafen", "tram", "10|Flughafen")]
    runtime = hass.data[DOMAIN]
    assert (await ws("start", route_id=route["id"]))["success"]
    first = runtime.runs.runs[route["id"]]
    # A second tap (double click, old screen) starts over instead of cancelling.
    assert (await ws("start", route_id=route["id"]))["success"]
    assert runtime.runs.runs[route["id"]] is not first
    # A car route without a time can't start.
    car_route = await _car_route(ws, hass)
    assert "set an arrival time" in (await ws("start", route_id=car_route["id"]))["error"]["message"]


async def test_timetable(hass: HomeAssistant, ws, transit, freezer) -> None:
    home = (await ws.state())["locations"][0]["id"]
    await ws("station/save", item={"location_id": home, "name": "Tram", "stop_ref": "x", "walk_minutes": 5})
    line = {"key": "10|Flughafen", "name": "10", "destination": "Flughafen"}
    route = (await ws("route/save", item={
        "name": "Work", "mode": "transit", "origin_id": home, "lines": [line],
    }))["result"]
    transit.result = [
        # Leave time already passed: left out.
        Departure(at(3), at(3), "10", "Flughafen", "tram", "10|Flughafen"),
        Departure(at(12), at(10), "10", "Flughafen", "tram", "10|Flughafen"),
        Departure(at(14), at(14), "14", "Triemli", "tram", "14|Triemli"),
        Departure(at(20), at(20), "10", "Flughafen", "tram", "10|Flughafen", cancelled=True),
        Departure(at(30), at(30), "10", "Flughafen", "tram", "10|Flughafen"),
    ]
    transit.calls.clear()
    assert (await ws("timetable", route_ids=[route["id"]], count=2, refresh=60))["success"]
    board = (await ws.event("boards"))["boards"][0]
    assert board["station"] == "Tram" and board["walk_minutes"] == 5
    assert [(d["planned_departure"], d["delay_minutes"], d["cancelled"]) for d in board["departures"]] == [
        (at(10).isoformat(), 2, False),
        (at(20).isoformat(), 0, True),
        (at(30).isoformat(), 0, False),
    ]
    assert board["departures"][0]["leave_at"] == at(7).isoformat()
    assert len(transit.calls) == 1

    # A second card on the same station shares the call.
    assert (await ws("timetable", count=5, refresh=30))["success"]
    assert (await ws.event("boards"))["boards"][0]["departures"]
    assert len(transit.calls) == 1

    assert not (await ws("timetable", refresh=10))["success"]


async def test_departure_sensors(hass: HomeAssistant, ws, transit, freezer) -> None:
    home = (await ws.state())["locations"][0]["id"]
    await ws("station/save", item={"location_id": home, "name": "Tram", "stop_ref": "x", "walk_minutes": 5})
    line = {"key": "10|Flughafen", "name": "10", "destination": "Flughafen"}
    item = {"name": "Work", "mode": "transit", "origin_id": home, "lines": [line]}
    transit.result = [
        Departure(at(12), at(10), "10", "Flughafen", "tram", "10|Flughafen", cancelled=True),
        Departure(at(14), at(12), "10", "Flughafen", "tram", "10|Flughafen"),
        Departure(at(15), at(15), "14", "Triemli", "tram", "14|Triemli"),
        Departure(at(30), at(30), "10", "Flughafen", "tram", "10|Flughafen"),
    ]
    # Without a window there are no sensors and no calls.
    route = (await ws("route/save", item=item))["result"]
    await hass.async_block_till_done()
    registry = er.async_get(hass)
    assert registry.async_get_entity_id("sensor", DOMAIN, f"{route['id']}_next_departure") is None
    assert not transit.calls

    bad = await ws("route/save", item={**route, "departure_windows": [{"days": [0]}]})
    assert bad["error"]["message"] == "Set when each departure sensor window starts and ends"

    # Monday 09:30-10:30 in Zurich; it's 10:00, every 2 minutes, 2 listed.
    # The weekend window lists more, but doesn't apply now.
    route = (await ws("route/save", item={**route, "departure_windows": [
        {"days": [5, 6], "from": "09:00", "to": "11:00", "every": 5, "count": 10},
        {"days": [0], "from": "09:30", "to": "10:30", "every": 2, "count": 2},
    ]}))["result"]
    await hass.async_block_till_done()
    await hass.async_block_till_done()
    next_ = registry.async_get_entity_id("sensor", DOMAIN, f"{route['id']}_next_departure")
    every = registry.async_get_entity_id("sensor", DOMAIN, f"{route['id']}_departures")
    # The cancelled one is skipped for "next"; the list keeps it.
    state = hass.states.get(next_)
    assert state.state == "10 Flughafen 10:14 +2, leave in 9 min"
    assert state.attributes["leave_in"] == 9
    assert state.attributes["text"] == "10 Flughafen 10:14 +2"
    listed = hass.states.get(every)
    assert listed.state == "2"
    assert [d["text"] for d in listed.attributes["departures"]] == [
        "10 Flughafen 10:12 cancelled", "10 Flughafen 10:14 +2"
    ]
    calls = len(transit.calls)

    # A minute later it counts down without asking again.
    freezer.tick(60)
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert hass.states.get(next_).state.endswith("leave in 8 min")
    assert len(transit.calls) == calls

    # After the window: unknown, no more calls.
    freezer.move_to(at(31))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert hass.states.get(next_).state == "unknown"
    assert hass.states.get(every).state == "unknown"


async def test_api_usage(hass: HomeAssistant, ws, freezer) -> None:
    runtime = hass.data[DOMAIN]
    assert (await ws.state())["usage"] == {
        "tomtom": {"calls": 0, "planned": 0, "limit": 2500},
        "ojp": {"calls": 0, "planned": 0, "limit": 20000},
    }
    runtime.usage.count("ojp")
    runtime.usage.count("ojp")
    runtime.usage.count("tomtom")
    assert (await ws("settings", changes={"limit_tomtom": 5000}))["success"]
    usage = ws.events[-1]["usage"]
    assert usage["tomtom"] == {"calls": 1, "planned": 0, "limit": 5000}
    assert usage["ojp"]["calls"] == 2

    # A new day (UTC) starts from zero.
    freezer.move_to(datetime(2026, 10, 20, 0, 1, tzinfo=dt_util.UTC))
    assert runtime.usage.as_dict()["ojp"]["calls"] == 0


async def test_providers_report_calls() -> None:
    session = MagicMock()
    session.post.side_effect = aiohttp.ClientError("down")
    session.get.side_effect = aiohttp.ClientError("down")
    calls = []
    ojp = OjpProvider(session, "key")
    ojp.on_call = lambda: calls.append("ojp")
    tomtom = TomTomProvider(session, "key")
    tomtom.on_call = lambda: calls.append("tomtom")
    with pytest.raises(HomeAssistantError):
        await ojp.search_stops("Zürich")
    with pytest.raises(HomeAssistantError):
        await tomtom.search_places("Bahnhofstrasse")
    # Failed calls count too: the provider may still have counted them.
    assert calls == ["ojp", "tomtom"]


async def test_planned_api_calls(hass: HomeAssistant, ws) -> None:
    home = (await ws.state())["locations"][0]["id"]
    gf = (await ws("location/save", item={"name": "GF", "latitude": 47.2, "longitude": 8.3}))["result"]
    await ws("station/save", item={"location_id": home, "name": "Tram", "stop_ref": "x", "walk_minutes": 5})
    line = {"key": "10|Flughafen", "name": "10", "destination": "Flughafen"}
    # Car watched Monday 18:00-23:00 (60 checks) and Sunday 23:00-01:00 (12 of them on Monday).
    for days, start, end in (([0], "18:00", "23:00"), ([6], "23:00", "01:00")):
        await ws("route/save", item={
            "name": f"Car {start}", "mode": "car", "origin_id": home, "destination_id": gf["id"],
            "watch_windows": [{"days": days, "from": start, "to": end}],
        })
    # Public transport watched Monday 06:30-08:00 (18 checks) and Tuesday 07:00-08:00 (12).
    await ws("route/save", item={
        "name": "Tram", "mode": "transit", "origin_id": home, "lines": [line],
        "watch_windows": [
            {"days": [0], "from": "06:30", "to": "08:00"},
            {"days": [1], "from": "07:00", "to": "08:00"},
        ],
        # Departure sensors every 2 minutes 06:00-07:00, every 4 minutes 07:00-08:00 ...
        "departure_windows": [
            {"days": [0], "from": "06:00", "to": "07:00", "every": 2},
            {"days": [0], "from": "07:00", "to": "08:00", "every": 4},
        ],
    })
    # ... and every minute 06:30-07:30 on the same station: shared, the shorter interval wins.
    # 06:00-06:30 every 2 (15) + 06:30-07:30 every minute (60) + 07:30-08:00 every 4 (7.5) = 82.5.
    await ws("route/save", item={
        "name": "Tram too", "mode": "transit", "origin_id": home, "lines": [line],
        "departure_windows": [{"days": [0], "from": "06:30", "to": "07:30", "every": 1}],
    })
    usage = hass.data[DOMAIN].usage
    assert usage.planned(date(2026, 10, 19)) == {"tomtom": 72, "ojp": round(18 + 82.5)}
    # Only the Tuesday watch window falls on Tuesday.
    assert usage.planned(date(2026, 10, 20)) == {"tomtom": 0, "ojp": 12}
