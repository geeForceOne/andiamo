"""Provider interfaces, so public transport and car routing can be swapped."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta

from homeassistant.exceptions import HomeAssistantError


class ProviderError(HomeAssistantError):
    """A provider call failed (network, key, unexpected answer)."""


@dataclass(frozen=True)
class Stop:
    """A public transport stop found by name."""

    ref: str
    name: str
    latitude: float | None = None
    longitude: float | None = None


@dataclass(frozen=True)
class Departure:
    """One public transport departure from the boarding station."""

    departure: datetime
    """Real-time departure (timetable if none)."""
    planned_departure: datetime
    line: str
    destination: str
    mode: str
    line_key: str
    """Identifies the line and its direction, to match the lines a route takes."""

    @property
    def delay(self) -> timedelta:
        return self.departure - self.planned_departure


@dataclass(frozen=True)
class Line:
    """A line and direction leaving a station, for the route form."""

    key: str
    name: str
    destination: str
    mode: str


@dataclass(frozen=True)
class Place:
    """An address found by search."""

    name: str
    latitude: float
    longitude: float


class TransitProvider(ABC):
    """Finds stops and the next departures from a stop."""

    @abstractmethod
    async def search_stops(self, query: str) -> list[Stop]:
        """Stops matching a name."""

    @abstractmethod
    async def departures(
        self, stop_ref: str, earliest: datetime, count: int = 100
    ) -> list[Departure]:
        """Departures from the stop at `earliest` or later, cancelled ones left out."""


class CarProvider(ABC):
    """Works out when to leave by car to arrive on time."""

    @abstractmethod
    async def departure_for_arrival(
        self,
        origin: tuple[float, float],
        destination: tuple[float, float],
        arrive_at: datetime,
    ) -> datetime:
        """The time to leave `origin` to reach `destination` by `arrive_at`."""

    @abstractmethod
    async def search_places(self, query: str) -> list[Place]:
        """Addresses matching a search text."""


def lines_of(departures: list[Departure]) -> list[Line]:
    """Each line and direction once, named after its most frequent destination."""
    destinations: dict[str, Counter[str]] = {}
    first: dict[str, Departure] = {}
    for departure in departures:
        first.setdefault(departure.line_key, departure)
        destinations.setdefault(departure.line_key, Counter())[departure.destination] += 1
    lines = [
        Line(
            key=key,
            name=d.line,
            destination=destinations[key].most_common(1)[0][0],
            mode=d.mode,
        )
        for key, d in first.items()
    ]
    lines.sort(key=lambda l: (_natural(l.name), l.destination))
    return lines


def _natural(name: str) -> tuple[int, str]:
    """Line 2 before line 10; named lines (S2, IC 5) after the numbers."""
    return (int(name), "") if name.isdigit() else (10**6, name)
