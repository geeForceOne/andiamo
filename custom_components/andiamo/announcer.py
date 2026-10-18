"""Says things on a speaker, or as a notification in test mode."""

from __future__ import annotations

import logging

from homeassistant.components import persistent_notification
from homeassistant.core import HomeAssistant

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
        if self.store.settings.get("test_mode") or not tts_entity or not speaker:
            persistent_notification.async_create(
                self.hass,
                message,
                title=f"Andiamo: {route['name']}",
                notification_id=f"{DOMAIN}_{route['id']}",
            )
            return
        try:
            await self.hass.services.async_call(
                "tts",
                "speak",
                {"media_player_entity_id": speaker, "message": message, "cache": True},
                target={"entity_id": tts_entity},
                blocking=False,
            )
        except Exception:  # noqa: BLE001 - a failing speaker must not stop the countdown
            _LOGGER.exception("Couldn't say %r on %s", message, speaker)
