"""Shared test setup."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from homeassistant.core import HomeAssistant

from custom_components.andiamo.announcer import Announcer
from custom_components.andiamo.providers import (
    CarProvider,
    Departure,
    Place,
    Stop,
    TransitProvider,
    Trip,
)
from custom_components.andiamo.runner import RunManager
from custom_components.andiamo.store import AndiamoStore

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(hass: HomeAssistant, enable_custom_integrations):
    # The real frontend package isn't part of the test environment.
    hass.config.components.update({"frontend", "panel_custom"})
    yield


def fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


class FakeTransit(TransitProvider):
    def __init__(self) -> None:
        self.result: list[Departure] = []
        self.calls: list[datetime] = []

    async def search_stops(self, query: str) -> list[Stop]:
        return [Stop("ch:1:sloid:1", query)]

    async def departures(self, stop_ref, earliest, count=100, include_cancelled=False):
        self.calls.append(earliest)
        return [
            d
            for d in self.result
            if d.departure >= earliest and (include_cancelled or not d.cancelled)
        ]


class FakeCar(CarProvider):
    def __init__(self) -> None:
        self.departure: datetime | None = None
        self.calls = 0
        # The arrival times asked for.
        self.arrivals: list[datetime] = []
        # Leaving now: (travel seconds, traffic delay seconds).
        self.now = (1800, 0)

    async def trip_for_arrival(self, origin, destination, arrive_at):
        self.calls += 1
        self.arrivals.append(arrive_at)
        assert self.departure is not None
        return Trip(self.departure, 2460, 180, 32411)

    async def trip_now(self, origin, destination):
        return Trip(datetime.now(), self.now[0], self.now[1], 32411)

    async def search_places(self, query: str) -> list[Place]:
        return [Place(query, 47.0, 8.0)]


@pytest.fixture
def transit() -> FakeTransit:
    return FakeTransit()


@pytest.fixture
def car() -> FakeCar:
    return FakeCar()


@pytest.fixture
async def store(hass: HomeAssistant) -> AndiamoStore:
    await hass.config.async_set_time_zone("Europe/Zurich")
    store = AndiamoStore(hass)
    await store.async_load()
    store.settings["announce"] = "notification"
    return store


@pytest.fixture
def runs(hass: HomeAssistant, store, transit, car) -> RunManager:
    manager = RunManager(hass, store, Announcer(hass, store), lambda: transit, lambda: car)
    yield manager
    manager.stop_all()
