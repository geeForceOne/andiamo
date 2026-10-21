"""Places, stations and routes: what a route needs and what can be deleted."""

from __future__ import annotations

import pytest

from homeassistant.core import HomeAssistant

from custom_components.andiamo.store import DataError, AndiamoStore


async def test_starts_with_home(hass: HomeAssistant, store: AndiamoStore) -> None:
    assert len(store.locations) == 1
    home = store.locations[0]
    assert "main" not in home
    assert (home["latitude"], home["longitude"]) == (
        hass.config.latitude,
        hass.config.longitude,
    )


async def test_route_keeps_a_real_station(store: AndiamoStore) -> None:
    home = store.locations[0]
    line = {"key": "10|Flughafen", "name": "10", "destination": "Flughafen"}
    route = {"name": "To work", "mode": "transit", "origin_id": home["id"], "lines": [line]}

    with pytest.raises(DataError, match="Add a station to"):
        await store.async_save_route(route)

    tram = await store.async_save_station(
        {"location_id": home["id"], "name": "Tram", "stop_ref": "a", "walk_minutes": 3}
    )
    train = await store.async_save_station(
        {"location_id": home["id"], "name": "Train", "stop_ref": "b", "walk_minutes": 12}
    )
    # None picked: the first one is stored, and stays when more are added.
    saved = await store.async_save_route(route)
    assert saved["station_id"] == tram["id"]
    assert store.route_station(saved) is tram
    saved = await store.async_save_route({**saved, "station_id": train["id"]})
    assert store.route_station(saved) is train


async def test_main_station_becomes_the_routes_own(hass: HomeAssistant, store: AndiamoStore) -> None:
    home = store.locations[0]
    home["main"] = True
    store.stations += [
        {"id": "s1", "location_id": home["id"], "name": "Tram", "stop_ref": "a", "walk_minutes": 3, "main": False},
        {"id": "s2", "location_id": home["id"], "name": "Train", "stop_ref": "b", "walk_minutes": 9, "main": True},
    ]
    store.routes.append(
        {"id": "r1", "name": "Old", "mode": "transit", "origin_id": home["id"], "station_id": None, "lines": []}
    )
    await store.async_save()

    again = AndiamoStore(hass)
    await again.async_load()
    # It boarded at the main station, and keeps doing so.
    assert again.routes[0]["station_id"] == "s2"
    assert not any("main" in item for item in (*again.locations, *again.stations))


async def test_route_checks(store: AndiamoStore) -> None:
    home = store.locations[0]
    work = await store.async_save_location({"name": "Work", "latitude": 47, "longitude": 8})
    office = await store.async_save_station(
        {"location_id": work["id"], "name": "Office", "stop_ref": "c", "walk_minutes": 1}
    )
    transit = {"name": "T", "mode": "transit", "origin_id": home["id"], "lines": [{"key": "10|Flughafen", "name": "10", "destination": "Flughafen"}]}
    base = {"name": "R", "mode": "car", "origin_id": home["id"], "destination_id": work["id"]}

    with pytest.raises(DataError, match="same"):
        await store.async_save_route({**base, "destination_id": home["id"]})
    with pytest.raises(DataError, match="Pick a destination"):
        await store.async_save_route({**base, "destination_id": None})
    with pytest.raises(DataError, match="doesn't belong"):
        await store.async_save_route({**transit, "station_id": office["id"]})
    with pytest.raises(DataError, match="at least one line"):
        await store.async_save_route({**transit, "lines": []})

    # A public transport route keeps no destination.
    tram = await store.async_save_station(
        {"location_id": home["id"], "name": "Tram", "stop_ref": "a", "walk_minutes": 3}
    )
    saved = await store.async_save_route({**transit, "destination_id": work["id"]})
    assert saved["destination_id"] is None
    await store.async_delete_route(saved["id"])

    route = await store.async_save_route(base)
    with pytest.raises(DataError, match="used by: R"):
        await store.async_delete_location(work["id"])

    await store.async_delete_route(route["id"])
    await store.async_delete_location(work["id"])
    assert store.stations == [tram]


async def test_saved_and_loaded(hass: HomeAssistant, store: AndiamoStore) -> None:
    await store.async_save_location({"name": "Work", "latitude": 47, "longitude": 8})
    await store.async_update_settings({"language": "en"})

    again = AndiamoStore(hass)
    await again.async_load()
    assert [l["name"] for l in again.locations] == [l["name"] for l in store.locations]
    assert again.settings["language"] == "en"
    assert again.settings["car_lead_minutes"] == 30


async def test_old_routes_cleaned_on_load(hass: HomeAssistant, store: AndiamoStore) -> None:
    home = store.locations[0]
    work = await store.async_save_location({"name": "Work", "latitude": 47, "longitude": 8})
    old = {
        "id": "r1", "name": "Old", "mode": "transit", "origin_id": home["id"],
        "destination_id": work["id"], "station_id": None, "speaker": "media_player.x",
        "buffer_minutes": 3,
    }
    store.routes.append(old)
    await store.async_save()

    again = AndiamoStore(hass)
    await again.async_load()
    assert again.routes == [
        {"id": "r1", "name": "Old", "mode": "transit", "origin_id": home["id"],
         "destination_id": None, "station_id": None, "speaker": "media_player.x",
         "lines": [], "announce": None, "reserve_minutes": None, "watch_windows": [],
         "departure_windows": []}
    ]


async def test_one_window_becomes_a_list(hass: HomeAssistant, store: AndiamoStore) -> None:
    home = store.locations[0]
    store.routes.append({
        "id": "r1", "name": "Old", "mode": "transit", "origin_id": home["id"], "lines": [],
        "watch_days": [0, 1], "watch_from": "06:30", "watch_to": "08:00", "problem_minutes": 10,
        "departures_days": [5], "departures_from": "09:00", "departures_to": "10:00",
        "departures_every": 3, "departures_count": 4,
    })
    await store.async_save()

    again = AndiamoStore(hass)
    await again.async_load()
    route = again.routes[0]
    assert route["watch_windows"] == [
        {"days": [0, 1], "from": "06:30", "to": "08:00", "problem_minutes": 10}
    ]
    assert route["departure_windows"] == [
        {"days": [5], "from": "09:00", "to": "10:00", "every": 3, "count": 4}
    ]
    assert "watch_days" not in route and "departures_every" not in route


async def test_old_car_runs_load(hass: HomeAssistant, store: AndiamoStore) -> None:
    store.car_runs = {"r1": "2026-10-19T10:00:00+00:00"}
    await store.async_save()
    again = AndiamoStore(hass)
    await again.async_load()
    assert again.car_runs == {"r1": {"arrive_at": "2026-10-19T10:00:00+00:00"}}


async def test_test_mode_becomes_announce_notification(hass: HomeAssistant, hass_storage) -> None:
    hass_storage["andiamo"] = {
        "version": 1,
        "key": "andiamo",
        "data": {"settings": {"test_mode": True}, "locations": [], "routes": []},
    }
    store = AndiamoStore(hass)
    await store.async_load()

    assert store.settings["announce"] == "notification"
    assert "test_mode" not in store.settings


async def test_watch_needs_start_and_end(store: AndiamoStore) -> None:
    home = store.locations[0]
    work = await store.async_save_location({"name": "Work", "latitude": 47, "longitude": 8})
    route = {"name": "Work", "mode": "car", "origin_id": home["id"], "destination_id": work["id"]}

    with pytest.raises(DataError, match="starts and ends"):
        await store.async_save_route({**route, "watch_windows": [{"days": [0], "from": "06:30"}]})
    with pytest.raises(DataError, match="Pick the days"):
        await store.async_save_route(
            {**route, "watch_windows": [{"days": [], "from": "06:30", "to": "08:00"}]}
        )
    saved = await store.async_save_route(
        {**route, "watch_windows": [{"days": [0], "from": "06:30", "to": "08:00"}]}
    )
    assert saved["watch_windows"][0]["days"] == [0]
