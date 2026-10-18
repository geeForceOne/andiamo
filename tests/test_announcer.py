"""Where announcements go: Alexa, a TTS engine in the right language, or a notification."""

from __future__ import annotations

import pytest
from pytest_homeassistant_custom_component.common import async_mock_service

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from custom_components.andiamo import announcer as announcer_module
from custom_components.andiamo.announcer import Announcer
from custom_components.andiamo.store import AndiamoStore

ROUTE = {"id": "r1", "name": "Work"}


@pytest.fixture
def speaking(store: AndiamoStore, monkeypatch) -> AndiamoStore:
    store.settings.update(test_mode=False, tts_entity="tts.cloud", speaker="media_player.kitchen")
    languages = ["en-US", "de-DE", "de-CH", "de-AT"]
    monkeypatch.setattr(announcer_module, "engine_languages", lambda hass, entity: languages)
    return store


async def test_tts_gets_the_closest_language(hass: HomeAssistant, speaking) -> None:
    hass.config.country = "CH"
    calls = async_mock_service(hass, "tts", "speak")

    await Announcer(hass, speaking).async_say("Los jetzt!", ROUTE, "media_player.kitchen")
    await hass.async_block_till_done()

    assert calls[0].data["language"] == "de-CH"
    assert calls[0].data["message"] == "Los jetzt!"


async def test_tts_english(hass: HomeAssistant, speaking) -> None:
    speaking.settings["language"] = "en"
    calls = async_mock_service(hass, "tts", "speak")

    await Announcer(hass, speaking).async_say("Go now!", ROUTE, "media_player.kitchen")
    await hass.async_block_till_done()

    assert calls[0].data["language"] == "en-US"


async def test_alexa_speaks_in_its_own_voice(hass: HomeAssistant, speaking) -> None:
    er.async_get(hass).async_get_or_create(
        "media_player", "alexa_media", "echo1", suggested_object_id="echo_office"
    )
    speaking.settings["tts_entity"] = None
    tts = async_mock_service(hass, "tts", "speak")
    alexa = async_mock_service(hass, "notify", "alexa_media")

    await Announcer(hass, speaking).async_say("Los jetzt!", ROUTE, "media_player.echo_office")
    await hass.async_block_till_done()

    assert not tts
    assert alexa[0].data == {
        "message": "Los jetzt!",
        "target": "media_player.echo_office",
        "data": {"type": "tts"},
    }
