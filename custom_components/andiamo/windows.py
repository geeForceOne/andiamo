"""Time windows of a route: days plus from/until, for the watchdog and the departure sensors."""

from __future__ import annotations

from datetime import datetime, time, timedelta
from typing import Any

DAY_NAMES = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
DAY = 24 * 60
WEEK = 7 * DAY


def in_window(window: dict[str, Any], now: datetime) -> bool:
    """Whether `now` (local time) falls in the window.

    A window that ends before it starts runs past midnight and belongs to the
    day it started on.
    """
    days = window.get("days") or []
    start, end = _time(window.get("from")), _time(window.get("to"))
    if not days or start is None or end is None:
        return False
    current = now.time().replace(second=0, microsecond=0)
    if start < end:
        return now.weekday() in days and start <= current < end
    if current >= start:
        return now.weekday() in days
    return current < end and (now - timedelta(days=1)).weekday() in days


def active(windows: list[dict[str, Any]] | None, now: datetime) -> dict[str, Any] | None:
    """The window `now` falls in, if any; saved windows never overlap."""
    return next((w for w in windows or [] if in_window(w, now)), None)


def check(windows: list[dict[str, Any]], what: str) -> None:
    """Raise ValueError when a window is incomplete or two windows overlap."""
    spans: list[tuple[int, int, int]] = []
    for index, window in enumerate(windows):
        start, end = _time(window.get("from")), _time(window.get("to"))
        if not window.get("days"):
            raise ValueError(f"Pick the days of each {what} window")
        if start is None or end is None:
            raise ValueError(f"Set when each {what} window starts and ends")
        if start == end:
            raise ValueError(f"A {what} window starts and ends at the same time")
        begin = start.hour * 60 + start.minute
        length = (end.hour * 60 + end.minute - begin) % DAY
        spans.extend((index, day * DAY + begin, day * DAY + begin + length) for day in window["days"])
    for i, (a, a_start, a_end) in enumerate(spans):
        for b, b_start, b_end in spans[i + 1 :]:
            if a == b:
                continue
            # Sunday night runs into Monday: compare a week earlier and later too.
            for shift in (-WEEK, 0, WEEK):
                low, high = max(a_start, b_start + shift), min(a_end, b_end + shift)
                if low < high:
                    raise ValueError(
                        f"{what.capitalize()} windows overlap on "
                        f"{DAY_NAMES[low % WEEK // DAY]} {_hhmm(low)}–{_hhmm(high)}"
                    )


def migrate(route: dict[str, Any], kind: str, fields: dict[str, str]) -> list[dict[str, Any]]:
    """The single window older versions stored as `<kind>_days/_from/_to`, as a list.

    `fields` maps the old route keys that went into the window to their window keys.
    """
    old = {key: route.pop(f"{kind}_{key}", None) for key in ("days", "from", "to")}
    values = {new: route.pop(key, None) for key, new in fields.items()}
    if not old["days"] or not old["from"] or not old["to"]:
        return []
    return [{**old, **{key: value for key, value in values.items() if value is not None}}]


def _time(value: str | None) -> time | None:
    try:
        return time.fromisoformat(value) if value else None
    except ValueError:
        return None


def _hhmm(minute: int) -> str:
    minute %= DAY
    return f"{minute // 60:02d}:{minute % 60:02d}"
