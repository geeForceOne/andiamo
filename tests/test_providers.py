"""Reading OJP and TomTom answers."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json

import pytest

from custom_components.andiamo.providers import ProviderError, lines_of
from custom_components.andiamo.providers.ojp import parse_departures, parse_stops
from custom_components.andiamo.providers.tomtom import parse_places, parse_trip

from .conftest import fixture

UTC = timezone.utc


def test_departures_sorted_without_cancelled() -> None:
    departures = parse_departures(fixture("ojp_stop_events.xml"))

    assert [(d.line, d.destination) for d in departures] == [
        ("31", "Schlieren"),
        ("10", "Flughafen"),
        ("31", "Schlieren"),
        ("31", "Farbhof"),
    ]
    bus, tram = departures[:2]
    assert bus.departure == datetime(2026, 10, 19, 8, 11, 30, tzinfo=UTC)
    assert bus.planned_departure == datetime(2026, 10, 19, 8, 10, tzinfo=UTC)
    assert bus.delay == timedelta(minutes=1, seconds=30)
    assert bus.mode == "bus"
    assert bus.line_key == "ojp:91031:R|R"
    # No real-time value: the timetable counts.
    assert tram.departure == tram.planned_departure


def test_lines_once_per_direction() -> None:
    lines = lines_of(parse_departures(fixture("ojp_stop_events.xml")))

    # The short-turn 31 to Farbhof is the same line and direction as Schlieren.
    assert [(l.name, l.destination, l.key) for l in lines] == [
        ("10", "Flughafen", "ojp:91010:H|H"),
        ("31", "Schlieren", "ojp:91031:R|R"),
    ]


def test_no_departures_is_empty() -> None:
    xml = '<OJP xmlns="http://www.vdv.de/ojp" xmlns:siri="http://www.siri.org.uk/siri"/>'
    assert parse_departures(xml) == []


def test_unreadable_answer() -> None:
    with pytest.raises(ProviderError):
        parse_departures("<html>")


def test_stops() -> None:
    stops = parse_stops(fixture("ojp_stops.xml"))

    assert [(s.ref, s.name) for s in stops] == [
        ("ch:1:sloid:7000", "Bern"),
        ("ch:1:sloid:90034", "Bern, Bärenpark"),
    ]
    assert stops[0].latitude == pytest.approx(46.94883)
    assert stops[1].latitude is None
    assert stops[0].modes == ("rail", "bus")
    assert stops[1].modes == ()


def test_tomtom_trip() -> None:
    trip = parse_trip(json.loads(fixture("tomtom_route.json")))
    assert trip.departure == datetime(2026, 10, 19, 16, 19, tzinfo=UTC)
    assert (trip.travel_seconds, trip.traffic_delay_seconds, trip.length_meters) == (
        2460, 180, 32411
    )


def test_tomtom_no_route() -> None:
    with pytest.raises(ProviderError):
        parse_trip({"routes": []})


def test_tomtom_places_skip_incomplete() -> None:
    places = parse_places(json.loads(fixture("tomtom_geocode.json")))
    assert len(places) == 1
    assert places[0].name == "Bahnhofstrasse 1, 8001 Zürich"
    assert (places[0].latitude, places[0].longitude) == (47.37174, 8.53902)


def test_cancelled_departures_on_request() -> None:
    departures = parse_departures(fixture("ojp_stop_events.xml"), include_cancelled=True)

    cancelled = [d for d in departures if d.cancelled]
    assert len(cancelled) == 1
    assert len(departures) == 5
