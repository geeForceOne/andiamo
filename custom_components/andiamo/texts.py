"""What the speaker says, in German (Swiss spelling, "du") and English."""

from __future__ import annotations

from datetime import datetime

from homeassistant.util import dt as dt_util

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


def text(language: str, key: str, **values: object) -> str:
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
