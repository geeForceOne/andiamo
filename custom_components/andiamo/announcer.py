"""Says things on a speaker, or as a notification in test mode."""

from __future__ import annotations

import logging

from homeassistant.components import persistent_notification
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.util import language as language_util

from .const import DOMAIN, EVENT_ANNOUNCEMENT
from .store import AndiamoStore

_LOGGER = logging.getLogger(__name__)


class Announcer:
    def __init__(self, hass: HomeAssistant, store: AndiamoStore) -> None:
        self.hass = hass
        self.store = store

    async def async_say(self, message: str, route: dict, speaker: str | None) -> None:
        """Speak `message`; every announcement is also fired as an event."""
        self.hass.bus.async_fire(
            EVENT_ANNOUNCEMENT,
            {"route_id": route["id"], "route": route["name"], "message": message},
        )
        tts_entity = self.store.settings.get("tts_entity")
        alexa = speaker is not None and self._is_alexa(speaker)
        if self.store.settings.get("test_mode") or not speaker or not (alexa or tts_entity):
            persistent_notification.async_create(
                self.hass,
                message,
                title=f"Andiamo: {route['name']}",
                notification_id=f"{DOMAIN}_{route['id']}",
            )
            return
        try:
            if alexa:
                # Echo speakers from Alexa Media Player talk in Alexa's own voice.
                await self.hass.services.async_call(
                    "notify",
                    "alexa_media",
                    {"message": message, "target": speaker, "data": {"type": "tts"}},
                    blocking=False,
                )
                return
            data = {"media_player_entity_id": speaker, "message": message, "cache": True}
            if language := self._tts_language(tts_entity):
                data["language"] = language
            await self.hass.services.async_call(
                "tts", "speak", data, target={"entity_id": tts_entity}, blocking=False
            )
        except Exception:  # noqa: BLE001 - a failing speaker must not stop the countdown
            _LOGGER.exception("Couldn't say %r on %s", message, speaker)

    def _is_alexa(self, speaker: str) -> bool:
        entry = er.async_get(self.hass).async_get(speaker)
        return entry is not None and entry.platform == "alexa_media"

    def _tts_language(self, tts_entity: str) -> str | None:
        """The engine's closest voice for the announcement language, e.g. de-CH in Switzerland.

        Without one the engine would read German text in its default (often English) voice.
        """
        supported = engine_languages(self.hass, tts_entity)
        if not supported:
            return None
        found = language_util.matches(
            self.store.settings["language"], supported, self.hass.config.country
        )
        return found[0] if found else None


def engine_languages(hass: HomeAssistant, tts_entity: str) -> list[str]:
    # Imported here: the tts component pulls in audio libraries at import time.
    from homeassistant.components.tts.helper import get_engine_instance

    engine = get_engine_instance(hass, tts_entity)
    return list(engine.supported_languages or []) if engine else []
