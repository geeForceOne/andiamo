"""Watchdog: time windows, traffic jams, delays and cancellations."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from custom_components.andiamo.providers import Departure, ProviderError
from custom_components.andiamo.store import AndiamoStore
from custom_components.andiamo.watchdog import Watchdog, in_window

# Monday 10:00 in Zurich.
START = datetime(2026, 10, 19, 8, 0, tzinfo=dt_util.UTC)
MONDAY = 0


def local(day: int, hour: int, minute: int = 0) -> datetime:
    """A time in Zurich in the test week (day 0 = Monday 19 Oct)."""
    return datetime(2026, 10, 19 + day, hour, minute, tzinfo=dt_util.get_time_zone("Europe/Zurich"))


def departure(minutes: float, delay: float = 0, cancelled: bool = False, line: str = "10") -> Departure:
    planned = START + timedelta(minutes=minutes)
    return Departure(
        departure=planned + timedelta(minutes=delay),
        planned_departure=planned,
        line=line,
        destination="Flughafen",
        mode="tram",
        line_key=f"{line}|Flughafen",
        cancelled=cancelled,
    )


@pytest.mark.parametrize(
    ("days", "start", "end", "now", "expected"),
    [
        ([MONDAY], "09:00", "11:00", local(0, 10), True),
        ([MONDAY], "09:00", "11:00", local(0, 11), False),
        ([MONDAY], "09:00", "11:00", local(1, 10), False),
        ([], "09:00", "11:00", local(0, 10), False),
        # Past midnight: belongs to the day it started.
        ([MONDAY], "23:00", "01:00", local(0, 23, 30), True),
        ([MONDAY], "23:00", "01:00", local(1, 0, 30), True),
        ([MONDAY], "23:00", "01:00", local(0, 0, 30), False),
    ],
)
def test_in_window(days, start, end, now, expected) -> None:
    route = {"watch_days": days, "watch_from": start, "watch_to": end}
    assert in_window(route, now) is expected


@pytest.fixture(autouse=True)
def clock(freezer):
    freezer.move_to(START)
    return freezer


@pytest.fixture
async def routes(store: AndiamoStore) -> dict[str, dict]:
    home = store.locations[0]
    work = await store.async_save_location({"name": "Work", "latitude": 47.4, "longitude": 8.5})
    await store.async_save_station(
        {"location_id": home["id"], "name": "Tram", "stop_ref": "ch:1:sloid:1", "walk_minutes": 5}
    )
    window = {"watch_days": [MONDAY], "watch_from": "09:00", "watch_to": "11:00", "problem_minutes": 15}
    transit = await store.async_save_route(
        {
            "name": "Tram",
            "mode": "transit",
            "origin_id": home["id"],
            "lines": [{"key": "10|Flughafen", "name": "10", "destination": "Flughafen"}],
            **window,
        }
    )
    car = await store.async_save_route(
        {"name": "Car", "mode": "car", "origin_id": home["id"], "destination_id": work["id"], **window}
    )
    return {"transit": transit, "car": car}


@pytest.fixture
def watchdog(hass: HomeAssistant, store, transit, car) -> Watchdog:
    return Watchdog(hass, store, lambda: transit, lambda: car)


async def test_traffic_jam_from_the_limit(watchdog: Watchdog, routes, car) -> None:
    car.now = (3000, 14 * 60)
    await watchdog.async_check()
    assert routes["car"]["id"] in watchdog.watching
    assert routes["car"]["id"] not in watchdog.problems

    car.now = (3000, 15 * 60)
    await watchdog.async_check()
    assert watchdog.problems[routes["car"]["id"]] == {
        "reason": "traffic",
        "delay_minutes": 15,
        "travel_minutes": 50,
    }


async def test_cancelled_departure(watchdog: Watchdog, routes, transit) -> None:
    transit.result = [departure(10, cancelled=True), departure(20)]
    await watchdog.async_check()

    problem = watchdog.problems[routes["transit"]["id"]]
    assert problem["reason"] == "cancelled"
    assert problem["line"] == "10"
    assert problem["departure"] == (START + timedelta(minutes=10)).isoformat()


async def test_delayed_departure(watchdog: Watchdog, routes, transit) -> None:
    transit.result = [departure(10, delay=5)]
    await watchdog.async_check()
    assert routes["transit"]["id"] not in watchdog.problems

    transit.result = [departure(10, delay=16)]
    await watchdog.async_check()
    problem = watchdog.problems[routes["transit"]["id"]]
    assert (problem["reason"], problem["delay_minutes"]) == ("delayed", 16)


async def test_only_departures_one_can_catch(watchdog: Watchdog, routes, transit) -> None:
    # Leaves before the 5-minute walk is done: not ours.
    transit.result = [departure(3, cancelled=True), departure(12)]
    await watchdog.async_check()
    assert routes["transit"]["id"] not in watchdog.problems


async def test_outside_the_window_clears(watchdog: Watchdog, routes, car, clock) -> None:
    car.now = (3000, 20 * 60)
    await watchdog.async_check()
    assert routes["car"]["id"] in watchdog.problems

    clock.move_to(START + timedelta(hours=2))
    await watchdog.async_check()
    assert routes["car"]["id"] not in watchdog.problems
    assert not watchdog.watching


async def test_failed_check_keeps_the_last_state(watchdog: Watchdog, routes, car) -> None:
    car.now = (3000, 20 * 60)
    await watchdog.async_check()

    async def failing(origin, destination):
        raise ProviderError("down")

    car.trip_now = failing
    await watchdog.async_check()
    assert routes["car"]["id"] in watchdog.problems
