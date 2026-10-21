"""Swiss public transport from opentransportdata.swiss (OJP 2.0, real-time)."""

from __future__ import annotations

from datetime import datetime
from xml.etree import ElementTree as ET
from xml.sax.saxutils import escape

import aiohttp

from homeassistant.util import dt as dt_util

from .base import Departure, ProviderError, Stop, TransitProvider

URL = "https://api.opentransportdata.swiss/ojp20"
REQUESTOR = "Andiamo_prod"
NS = {"o": "http://www.vdv.de/ojp", "s": "http://www.siri.org.uk/siri"}
TIMEOUT = aiohttp.ClientTimeout(total=20)


class OjpProvider(TransitProvider):
    """OJP 2.0 with an API key from the opentransportdata.swiss API Manager."""

    def __init__(
        self, session: aiohttp.ClientSession, api_key: str, language: str = "de"
    ) -> None:
        self._session = session
        self._api_key = api_key
        self._language = language

    async def search_stops(self, query: str) -> list[Stop]:
        body = f"""
<OJPLocationInformationRequest>
  <siri:RequestTimestamp>{_now()}</siri:RequestTimestamp>
  <InitialInput><Name>{escape(query)}</Name></InitialInput>
  <Restrictions>
    <Type>stop</Type>
    <NumberOfResults>10</NumberOfResults>
    <IncludePtModes>true</IncludePtModes>
  </Restrictions>
</OJPLocationInformationRequest>"""
        return parse_stops(await self._post(body))

    async def departures(
        self,
        stop_ref: str,
        earliest: datetime,
        count: int = 100,
        include_cancelled: bool = False,
    ) -> list[Departure]:
        body = f"""
<OJPStopEventRequest>
  <siri:RequestTimestamp>{_now()}</siri:RequestTimestamp>
  <Location>
    <PlaceRef><StopPlaceRef>{escape(stop_ref)}</StopPlaceRef></PlaceRef>
    <DepArrTime>{_iso(earliest)}</DepArrTime>
  </Location>
  <Params>
    <NumberOfResults>{count}</NumberOfResults>
    <StopEventType>departure</StopEventType>
    <IncludePreviousCalls>false</IncludePreviousCalls>
    <IncludeOnwardCalls>false</IncludeOnwardCalls>
    <UseRealtimeData>explanatory</UseRealtimeData>
  </Params>
</OJPStopEventRequest>"""
        return parse_departures(await self._post(body), include_cancelled)

    async def _post(self, request: str) -> str:
        xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<OJP xmlns="http://www.vdv.de/ojp" xmlns:siri="http://www.siri.org.uk/siri" version="2.0">
<OJPRequest>
<siri:ServiceRequest>
  <siri:ServiceRequestContext><siri:Language>{self._language}</siri:Language></siri:ServiceRequestContext>
  <siri:RequestTimestamp>{_now()}</siri:RequestTimestamp>
  <siri:RequestorRef>{REQUESTOR}</siri:RequestorRef>
  {request}
</siri:ServiceRequest>
</OJPRequest>
</OJP>"""
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/xml",
        }
        self.counted()
        try:
            async with self._session.post(
                URL, data=xml.encode(), headers=headers, timeout=TIMEOUT
            ) as response:
                if response.status != 200:
                    detail = (await response.text())[:200]
                    if response.status in (401, 403):
                        raise ProviderError(f"The OJP API key was rejected: {detail}")
                    raise ProviderError(f"OJP answered with HTTP {response.status}: {detail}")
                return await response.text()
        except (aiohttp.ClientError, TimeoutError) as err:
            raise ProviderError(f"OJP can't be reached: {err}") from err


def parse_stops(xml: str) -> list[Stop]:
    root = _parse(xml)
    stops = []
    for place in root.iterfind(".//o:PlaceResult/o:Place", NS):
        ref = place.findtext("o:StopPlace/o:StopPlaceRef", namespaces=NS)
        name = place.findtext("o:StopPlace/o:StopPlaceName/o:Text", namespaces=NS)
        if not ref or not name:
            continue
        lon = place.findtext("o:GeoPosition/s:Longitude", namespaces=NS)
        lat = place.findtext("o:GeoPosition/s:Latitude", namespaces=NS)
        modes = dict.fromkeys(m.text for m in place.iterfind("o:Mode/o:PtMode", NS) if m.text)
        stops.append(
            Stop(
                ref=ref,
                name=name,
                latitude=float(lat) if lat else None,
                longitude=float(lon) if lon else None,
                modes=tuple(modes),
            )
        )
    return stops


def parse_departures(xml: str, include_cancelled: bool = False) -> list[Departure]:
    """Departures in time order, cancelled ones only if asked."""
    root = _parse(xml)
    departures = []
    for event in root.iterfind(".//o:StopEventResult/o:StopEvent", NS):
        departure = _departure(event)
        if departure is not None and (include_cancelled or not departure.cancelled):
            departures.append(departure)
    departures.sort(key=lambda d: d.departure)
    return departures


def _departure(event: ET.Element) -> Departure | None:
    service = event.find("o:Service", NS)
    if service is None:
        return None
    board = event.find("o:ThisCall/o:CallAtStop/o:ServiceDeparture", NS)
    if board is None:
        return None
    planned = board.findtext("o:TimetabledTime", namespaces=NS)
    if planned is None:
        return None
    estimated = board.findtext("o:EstimatedTime", namespaces=NS) or planned
    line = service.findtext("o:PublishedServiceName/o:Text", "", NS)
    destination = service.findtext("o:DestinationText/o:Text", "", NS)
    line_ref = service.findtext("s:LineRef", "", NS)
    direction = service.findtext("s:DirectionRef", "", NS)
    # Line and direction refs survive short-turn trips with another destination.
    key = f"{line_ref}|{direction}" if line_ref else f"{line}|{destination}"
    return Departure(
        departure=_time(estimated),
        planned_departure=_time(planned),
        line=line,
        destination=destination,
        mode=service.findtext("o:Mode/o:PtMode", "", NS),
        line_key=key,
        cancelled=service.findtext("o:Cancelled", "", NS) == "true",
    )


def _parse(xml: str) -> ET.Element:
    try:
        root = ET.fromstring(xml)
    except ET.ParseError as err:
        raise ProviderError(f"OJP sent an unreadable answer: {err}") from err
    # An ErrorCondition such as "no trip found" just means no results.
    return root


def _time(value: str) -> datetime:
    parsed = dt_util.parse_datetime(value)
    if parsed is None:
        raise ProviderError(f"OJP sent an unreadable time: {value}")
    return dt_util.as_utc(parsed)


def _iso(value: datetime) -> str:
    return dt_util.as_utc(value).strftime("%Y-%m-%dT%H:%M:%SZ")


def _now() -> str:
    return _iso(dt_util.utcnow())
