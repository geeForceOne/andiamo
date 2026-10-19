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
            ROUTE_URL.format(locations=locations), {"travelMode": "car", "traffic": "true"}
        )
        return parse_trip(data)

    async def search_places(self, query: str) -> list[Place]:
        params = {"limit": "8", "language": LANGUAGE_TAGS.get(self._language, "de-DE")}
        if self._bias:
            params["lat"], params["lon"] = str(self._bias[0]), str(self._bias[1])
        data = await self._get(GEOCODE_URL.format(query=quote(query, safe="")), params)
        return parse_places(data)

    async def _get(self, url: str, params: dict[str, str]) -> dict[str, Any]:
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
        summary = data["routes"][0]["summary"]
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
    )


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
