"""Countdowns with a fake clock: what is said, and when."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from pytest_homeassistant_custom_component.common import (
    async_capture_events,
    async_fire_time_changed,
)

from custom_components.andiamo.const import EVENT_ANNOUNCEMENT
from custom_components.andiamo.providers import Departure, ProviderError
from custom_components.andiamo.runner import RunManager
from custom_components.andiamo.store import DataError, AndiamoStore

# 10:00 in Zurich.
START = datetime(2026, 10, 19, 8, 0, tzinfo=dt_util.UTC)


def at(minutes: float) -> datetime:
    return START + timedelta(minutes=minutes)


def connection(minutes: float, delay: float = 0, line: str = "10") -> Departure:
    planned = at(minutes)
    return Departure(
        departure=planned + timedelta(minutes=delay),
        planned_departure=planned,
        line=line,
        destination="Flughafen",
        mode="tram",
        line_key=f"{line}|Flughafen",
    )


@pytest.fixture
async def routes(store: AndiamoStore) -> dict[str, dict]:
    home = store.locations[0]
    work = await store.async_save_location({"name": "Work", "latitude": 47.4, "longitude": 8.5})
    gf = await store.async_save_location({"name": "Girlfriend", "latitude": 47.2, "longitude": 8.3})
    await store.async_save_station(
        {"location_id": home["id"], "name": "Tram", "stop_ref": "ch:1:sloid:1", "walk_minutes": 5}
    )
    transit = await store.async_save_route(
        {"name": "Work", "mode": "transit", "origin_id": home["id"], "lines": [{"key": "10|Flughafen", "name": "10", "destination": "Flughafen"}]}
    )
    car = await store.async_save_route(
        {"name": "Girlfriend", "mode": "car", "origin_id": home["id"], "destination_id": gf["id"]}
    )
    return {"transit": transit, "car": car}


@pytest.fixture
def said(hass: HomeAssistant):
    events = async_capture_events(hass, EVENT_ANNOUNCEMENT)

    def messages() -> list[str]:
        return [e.data["message"] for e in events]

    return messages


@pytest.fixture(autouse=True)
def clock(freezer):
    freezer.move_to(START)
    return freezer


async def go_to(hass: HomeAssistant, clock, when: datetime) -> None:
    """Move the clock minute by minute, so every timer on the way fires."""
    now = dt_util.utcnow()
    while now < when:
        now = min(now + timedelta(minutes=1), when)
        clock.move_to(now)
        async_fire_time_changed(hass, now)
        await hass.async_block_till_done()


async def test_transit_leave_reminder_go(
    hass: HomeAssistant, runs: RunManager, routes, transit, said, clock
) -> None:
    # 10:03 can't be caught any more (5 min walk), so 10:12 it is.
    transit.result = [connection(3), connection(12)]

    await runs.async_press(routes["transit"]["id"])
    assert said() == ["Du musst um 10:07 los, das ist in 7 Minuten."]
    # Asked for connections leaving once we can be at the station.
    assert transit.calls[0] == at(5)

    await go_to(hass, clock, at(5))
    assert said()[1:] == ["Du hast noch 2 Minuten."]

    await go_to(hass, clock, at(7))
    assert said()[2:] == ["Los jetzt!"]
    assert runs.runs == {}


async def test_transit_follows_delay(
    hass: HomeAssistant, runs: RunManager, routes, transit, said, clock
) -> None:
    transit.result = [connection(12)]
    await runs.async_press(routes["transit"]["id"])

    # The tram is now 3 minutes late.
    transit.result = [connection(12, delay=3)]
    await go_to(hass, clock, at(1))
    assert said()[1:] == ["Neue Zeit: Du musst um 10:10 los, das ist in 9 Minuten."]

    await go_to(hass, clock, at(7))
    assert "Los jetzt!" not in said()
    await go_to(hass, clock, at(10))
    assert said()[-2:] == ["Du hast noch 2 Minuten.", "Los jetzt!"]


async def test_transit_small_delay_is_quiet(
    hass: HomeAssistant, runs: RunManager, routes, transit, said, clock
) -> None:
    transit.result = [connection(12)]
    await runs.async_press(routes["transit"]["id"])
    transit.result = [connection(12, delay=0.5)]
    await go_to(hass, clock, at(3))
    assert len(said()) == 1


async def test_transit_press_again_cancels(
    hass: HomeAssistant, runs: RunManager, routes, transit, said, clock
) -> None:
    transit.result = [connection(12)]
    await runs.async_press(routes["transit"]["id"])
    await runs.async_press(routes["transit"]["id"])

    assert said()[1:] == ["Abgebrochen."]
    await go_to(hass, clock, at(10))
    assert len(said()) == 2


async def test_transit_no_connection(
    hass: HomeAssistant, runs: RunManager, routes, transit, said
) -> None:
    with pytest.raises(DataError):
        await runs.async_press(routes["transit"]["id"])
    assert said() == ["Ich finde keine Verbindung für Work."]
    assert runs.runs == {}


async def test_transit_only_ticked_lines(
    hass: HomeAssistant, runs: RunManager, routes, transit, said
) -> None:
    # The 31 leaves first, but the route only takes the 10.
    transit.result = [connection(8, line="31"), connection(12)]
    await runs.async_press(routes["transit"]["id"])
    assert said() == ["Du musst um 10:07 los, das ist in 7 Minuten."]


async def test_transit_without_lines_cant_start(
    hass: HomeAssistant, runs: RunManager, store, routes, transit, said
) -> None:
    routes["transit"]["lines"] = []
    with pytest.raises(DataError, match="Pick a line"):
        await runs.async_press(routes["transit"]["id"])
    assert said() == []
    assert runs.runs == {}


async def test_transit_english(
    hass: HomeAssistant, runs: RunManager, store, routes, transit, said
) -> None:
    store.settings["language"] = "en"
    transit.result = [connection(6)]
    await runs.async_press(routes["transit"]["id"])
    assert said() == ["You need to leave at 10:01, that is in 1 minute."]


async def test_car_countdown(
    hass: HomeAssistant, runs: RunManager, store, routes, car, said, clock
) -> None:
    # Arrive 12:00, leave 11:20: quiet until 10:50.
    car.departure = at(80)
    await runs.async_start_car(routes["car"]["id"], at(120))
    assert said() == []
    assert routes["car"]["id"] in store.car_runs

    await go_to(hass, clock, at(49))
    assert said() == []

    await go_to(hass, clock, at(80))
    assert said() == [
        "Du hast noch 30 Minuten.",
        "Du hast noch 25 Minuten.",
        "Du hast noch 20 Minuten.",
        "Du hast noch 15 Minuten.",
        "Du hast noch 10 Minuten.",
        "Du hast noch 5 Minuten.",
        "Los jetzt!",
    ]
    assert runs.runs == {}
    assert store.car_runs == {}


async def test_car_checks_rarely_when_far(
    hass: HomeAssistant, runs: RunManager, routes, car, clock
) -> None:
    car.departure = at(180)
    await runs.async_start_car(routes["car"]["id"], at(220))
    await go_to(hass, clock, at(60))
    # One plan, then every 15 minutes.
    assert car.calls == 5


async def test_car_traffic_change(
    hass: HomeAssistant, runs: RunManager, routes, car, said, clock
) -> None:
    car.departure = at(40)
    await runs.async_start_car(routes["car"]["id"], at(80))
    await go_to(hass, clock, at(10))
    assert said() == ["Du hast noch 30 Minuten."]

    # Traffic: leave 3 minutes earlier.
    car.departure = at(37)
    await go_to(hass, clock, at(12))
    assert said()[1:] == [
        "Der Verkehr hat sich geändert: Du musst um 10:37 los, das ist in 25 Minuten."
    ]
    await go_to(hass, clock, at(37))
    assert said()[-1] == "Los jetzt!"
    assert "Du hast noch 5 Minuten." in said()


async def test_car_starts_inside_countdown(
    hass: HomeAssistant, runs: RunManager, routes, car, said, clock
) -> None:
    car.departure = at(12)
    await runs.async_start_car(routes["car"]["id"], at(40))
    assert said() == ["Du musst um 10:12 los, das ist in 12 Minuten."]
    await go_to(hass, clock, at(12))
    assert said()[1:] == ["Du hast noch 10 Minuten.", "Du hast noch 5 Minuten.", "Los jetzt!"]


async def test_car_already_late(
    hass: HomeAssistant, runs: RunManager, store, routes, car, said
) -> None:
    car.departure = at(-5)
    await runs.async_start_car(routes["car"]["id"], at(30))
    assert said() == ["Los jetzt!"]
    assert runs.runs == {}
    assert store.car_runs == {}


async def test_car_cancel_quiet_before_countdown(
    hass: HomeAssistant, runs: RunManager, routes, car, said
) -> None:
    car.departure = at(120)
    await runs.async_start_car(routes["car"]["id"], at(160))
    await runs.async_cancel(routes["car"]["id"])
    assert said() == []
    assert runs.runs == {}


async def test_car_resumes_after_restart(
    hass: HomeAssistant, runs: RunManager, store, routes, transit, car, said, clock
) -> None:
    car.departure = at(60)
    await runs.async_start_car(routes["car"]["id"], at(100))
    runs.stop_all()

    again = RunManager(hass, store, runs.announcer, lambda: transit, lambda: car)
    await again.async_resume()
    assert routes["car"]["id"] in again.runs
    await go_to(hass, clock, at(60))
    assert said()[-1] == "Los jetzt!"
    again.stop_all()


async def test_car_resume_retries_when_provider_fails(
    hass: HomeAssistant, runs: RunManager, store, routes, transit, car, said, clock
) -> None:
    store.car_runs[routes["car"]["id"]] = at(100).isoformat()

    async def failing(*args):
        raise ProviderError("offline")

    working = car.departure_for_arrival
    car.departure_for_arrival = failing
    await runs.async_resume()
    assert runs.runs[routes["car"]["id"]].leave_at is None

    car.departure_for_arrival = working
    car.departure = at(60)
    await go_to(hass, clock, at(3))
    assert runs.runs[routes["car"]["id"]].leave_at == at(60)


async def test_car_route_needs_time(runs: RunManager, routes) -> None:
    with pytest.raises(DataError, match="car route"):
        await runs.async_press(routes["car"]["id"])
    with pytest.raises(DataError, match="passed"):
        await runs.async_start_car(routes["car"]["id"], at(-1))
