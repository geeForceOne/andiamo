"""Car routing and address search from TomTom (live and predicted traffic)."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from urllib.parse import quote

import aiohttp

from homeassistant.util import dt as dt_util

from .base import CarProvider, Place, ProviderError, Trip

ROUTE_URL = "https://api.tomtom.com/routing/1/calculateRoute/{locations}/json"
GEOCODE_URL = "https://api.tomtom.com/search/2/geocode/{query}.json"
TIMEOUT = aiohttp.ClientTimeout(total=20)
# Instructions name the roads, traffic sections say where the delays are.
ROUTE_DETAILS = {"instructionsType": "coded", "sectionType": "traffic"}
# Delays shorter than this aren't worth naming a road for.
JAM_SECONDS = 60
# TomTom wants full language tags.
LANGUAGE_TAGS = {"de": "de-DE", "en": "en-GB"}


class TomTomProvider(CarProvider):
    """TomTom Routing (`arriveAt` plans backwards from the arrival time)."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        api_key: str,
        language: str = "de",
        bias: tuple[float, float] | None = None,
    ) -> None:
        self._session = session
        self._api_key = api_key
        self._language = language
        self._bias = bias

    async def trip_for_arrival(
        self,
        origin: tuple[float, float],
        destination: tuple[float, float],
        arrive_at: datetime,
    ) -> Trip:
        locations = f"{origin[0]},{origin[1]}:{destination[0]},{destination[1]}"
        data = await self._get(
            ROUTE_URL.format(locations=locations),
            {
                "travelMode": "car",
                "traffic": "true",
                **ROUTE_DETAILS,
                "arriveAt": dt_util.as_utc(arrive_at).strftime("%Y-%m-%dT%H:%M:%SZ"),
            },
        )
        return parse_trip(data)

    async def trip_now(
        self, origin: tuple[float, float], destination: tuple[float, float]
    ) -> Trip:
        # Without departAt TomTom leaves now, with live traffic.
        locations = f"{origin[0]},{origin[1]}:{destination[0]},{destination[1]}"
        data = await self._get(
            ROUTE_URL.format(locations=locations),
            {"travelMode": "car", "traffic": "true", **ROUTE_DETAILS},
        )
        return parse_trip(data)

    async def search_places(self, query: str) -> list[Place]:
        params = {"limit": "8", "language": LANGUAGE_TAGS.get(self._language, "de-DE")}
        if self._bias:
            params["lat"], params["lon"] = str(self._bias[0]), str(self._bias[1])
        data = await self._get(GEOCODE_URL.format(query=quote(query, safe="")), params)
        return parse_places(data)

    async def _get(self, url: str, params: dict[str, str]) -> dict[str, Any]:
        self.counted()
        try:
            async with self._session.get(
                url, params={**params, "key": self._api_key}, timeout=TIMEOUT
            ) as response:
                if response.status in (401, 403):
                    raise ProviderError("The TomTom API key was rejected")
                if response.status != 200:
                    detail = (await response.text())[:200]
                    raise ProviderError(
                        f"TomTom answered with HTTP {response.status}: {detail}"
                    )
                return await response.json()
        except (aiohttp.ClientError, TimeoutError) as err:
            raise ProviderError(f"TomTom can't be reached: {err}") from err


def parse_trip(data: dict[str, Any]) -> Trip:
    try:
        route = data["routes"][0]
        summary = route["summary"]
        value = summary["departureTime"]
    except (KeyError, IndexError, TypeError) as err:
        raise ProviderError("TomTom found no route") from err
    parsed = dt_util.parse_datetime(value)
    if parsed is None:
        raise ProviderError(f"TomTom sent an unreadable time: {value}")
    return Trip(
        departure=dt_util.as_utc(parsed),
        travel_seconds=int(summary.get("travelTimeInSeconds", 0)),
        traffic_delay_seconds=int(summary.get("trafficDelayInSeconds", 0)),
        length_meters=int(summary.get("lengthInMeters", 0)),
        via=main_road(route),
        jam_road=jam_road(route),
    )


def _instructions(route: dict[str, Any]) -> list[dict[str, Any]]:
    instructions = (route.get("guidance") or {}).get("instructions") or []
    return [i for i in instructions if isinstance(i, dict)]


def road_name(instruction: dict[str, Any]) -> str | None:
    """A motorway or national road number ("A4") if there is one, else the street."""
    numbers = [n for n in instruction.get("roadNumbers") or [] if isinstance(n, str) and n]
    lettered = [n for n in numbers if n[0].isalpha()]
    return (lettered or [None])[0] or instruction.get("street") or (numbers or [None])[0]


def main_road(route: dict[str, Any]) -> str | None:
    """The road driven the furthest; each instruction's road runs until the next one."""
    instructions = _instructions(route)
    meters: dict[str, int] = {}
    for current, following in zip(instructions, instructions[1:]):
        name = road_name(current)
        if name:
            stretch = following.get("routeOffsetInMeters", 0) - current.get("routeOffsetInMeters", 0)
            meters[name] = meters.get(name, 0) + max(0, stretch)
    return max(meters, key=meters.__getitem__) if meters else None


def jam_road(route: dict[str, Any]) -> str | None:
    """The road where the biggest delay starts, if one is long enough to mention."""
    jams = [
        s for s in route.get("sections") or []
        if s.get("sectionType") == "TRAFFIC" and s.get("delayInSeconds", 0) >= JAM_SECONDS
    ]
    if not jams:
        return None
    start = max(jams, key=lambda s: s["delayInSeconds"]).get("startPointIndex", 0)
    before = [i for i in _instructions(route) if i.get("pointIndex", 0) <= start]
    return road_name(before[-1]) if before else None


def parse_places(data: dict[str, Any]) -> list[Place]:
    places = []
    for result in data.get("results", []):
        try:
            places.append(
                Place(
                    name=result["address"]["freeformAddress"],
                    latitude=float(result["position"]["lat"]),
                    longitude=float(result["position"]["lon"]),
                )
            )
        except (KeyError, TypeError, ValueError):
            continue
    return places
