"""Places, stations and routes: main flags and what can be deleted."""

from __future__ import annotations

import pytest

from homeassistant.core import HomeAssistant

from custom_components.andiamo.store import DataError, AndiamoStore


async def test_starts_with_home_as_main(hass: HomeAssistant, store: AndiamoStore) -> None:
    assert len(store.locations) == 1
    home = store.locations[0]
    assert home["main"] is True
    assert (home["latitude"], home["longitude"]) == (
        hass.config.latitude,
        hass.config.longitude,
    )


async def test_one_main_location(store: AndiamoStore) -> None:
    home = store.locations[0]
    work = await store.async_save_location({"name": "Work", "latitude": 47, "longitude": 8})
    assert work["main"] is False

    await store.async_save_location({**work, "main": True})
    assert [l["main"] for l in store.locations] == [False, True]

    await store.async_delete_location(work["id"])
    assert home["main"] is True


async def test_one_main_station_per_location(store: AndiamoStore) -> None:
    home = store.locations[0]
    work = await store.async_save_location({"name": "Work", "latitude": 47, "longitude": 8})
    tram = await store.async_save_station(
        {"location_id": home["id"], "name": "Tram", "stop_ref": "a", "walk_minutes": 3}
    )
    train = await store.async_save_station(
        {"location_id": home["id"], "name": "Train", "stop_ref": "b", "walk_minutes": 12}
    )
    office = await store.async_save_station(
        {"location_id": work["id"], "name": "Office", "stop_ref": "c", "walk_minutes": 1}
    )
    # The first station of a location becomes its main one.
    assert (tram["main"], train["main"], office["main"]) == (True, False, True)

    await store.async_save_station({**train, "main": True})
    assert (tram["main"], train["main"], office["main"]) == (False, True, True)
    assert store.main_station(home["id"]) is train


async def test_route_uses_main_station_unless_set(store: AndiamoStore) -> None:
    home = store.locations[0]
    work = await store.async_save_location({"name": "Work", "latitude": 47, "longitude": 8})
    route = {"name": "To work", "mode": "transit", "origin_id": home["id"]}

    with pytest.raises(DataError, match="no station"):
        store.route_station(route)

    tram = await store.async_save_station(
        {"location_id": home["id"], "name": "Tram", "stop_ref": "a", "walk_minutes": 3}
    )
    train = await store.async_save_station(
        {"location_id": home["id"], "name": "Train", "stop_ref": "b", "walk_minutes": 12}
    )
    assert store.route_station(route) is tram
    assert store.route_station({**route, "station_id": train["id"]}) is train


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
    saved = await store.async_save_route({**transit, "destination_id": work["id"]})
    assert saved["destination_id"] is None
    await store.async_delete_route(saved["id"])

    route = await store.async_save_route(base)
    with pytest.raises(DataError, match="used by: R"):
        await store.async_delete_location(work["id"])

    await store.async_delete_route(route["id"])
    await store.async_delete_location(work["id"])
    assert store.stations == []


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
         "lines": []}
    ]


async def test_old_car_runs_load(hass: HomeAssistant, store: AndiamoStore) -> None:
    store.car_runs = {"r1": "2026-10-19T10:00:00+00:00"}
    await store.async_save()
    again = AndiamoStore(hass)
    await again.async_load()
    assert again.car_runs == {"r1": {"arrive_at": "2026-10-19T10:00:00+00:00"}}
