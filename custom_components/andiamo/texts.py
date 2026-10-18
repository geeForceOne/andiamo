"""What the speaker says, in German (Swiss spelling, "du") and English."""

from __future__ import annotations

from datetime import datetime
import logging
from string import Formatter

from homeassistant.util import dt as dt_util

_LOGGER = logging.getLogger(__name__)

TEXTS: dict[str, dict[str, str]] = {
    "de": {
        "leave_at": "Du musst um {time} los, das ist in {minutes}.",
        "changed": "Neue Zeit: Du musst um {time} los, das ist in {minutes}.",
        "traffic_changed": "Der Verkehr hat sich geändert: Du musst um {time} los, das ist in {minutes}.",
        "minutes_left": "Du hast noch {minutes}.",
        "go_now": "Los jetzt!",
        "cancelled": "Abgebrochen.",
        "no_connection": "Ich finde keine Verbindung für {route}.",
        "minute": "1 Minute",
        "minutes": "{n} Minuten",
    },
    "en": {
        "leave_at": "You need to leave at {time}, that is in {minutes}.",
        "changed": "New time: you need to leave at {time}, that is in {minutes}.",
        "traffic_changed": "Traffic has changed: you need to leave at {time}, that is in {minutes}.",
        "minutes_left": "You have {minutes} left.",
        "go_now": "Go now!",
        "cancelled": "Cancelled.",
        "no_connection": "I can't find a connection for {route}.",
        "minute": "1 minute",
        "minutes": "{n} minutes",
    },
}


# Messages the user can replace in Settings, and what they can put in them.
MESSAGES = (
    "leave_at", "changed", "traffic_changed", "minutes_left", "go_now", "cancelled", "no_connection",
)
PLACEHOLDERS = ("time", "minutes", "route", "line", "destination", "departure")


def unknown_placeholders(template: str) -> list[str]:
    """Placeholders that aren't offered, e.g. a typo like {tme} or {route.name}."""
    try:
        fields = [field for _, field, _, _ in Formatter().parse(template) if field is not None]
    except ValueError:  # an unmatched brace
        return [template]
    return [field for field in fields if field not in PLACEHOLDERS]


def text(
    language: str, key: str, templates: dict[str, str] | None = None, **values: object
) -> str:
    """The message from the user's template if there is one, else the built-in text."""
    template = (templates or {}).get(key)
    if template and not unknown_placeholders(template):
        return template.format_map({name: "" for name in PLACEHOLDERS} | values)
    if template:
        _LOGGER.warning("Message template %r has unknown placeholders, using the default", key)
    texts = TEXTS.get(language, TEXTS["de"])
    return texts[key].format(**values)


def minutes(language: str, count: int) -> str:
    if count == 1:
        return text(language, "minute")
    return text(language, "minutes", n=count)


def clock(value: datetime) -> str:
    return dt_util.as_local(value).strftime("%H:%M")


def minutes_until(target: datetime, now: datetime) -> int:
    """Whole minutes left, rounded so 6:40 left is said as 7 minutes."""
    return max(0, round((target - now).total_seconds() / 60))
