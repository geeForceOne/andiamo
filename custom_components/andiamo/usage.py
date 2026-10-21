"""Counts Andiamo's API calls per day, and plans them from the setup, against the free daily limits."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Any

from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import async_call_later
from homeassistant.util import dt as dt_util

from .const import MODE_CAR, MODE_TRANSIT, SIGNAL_USAGE_CHANGED, WATCH_INTERVAL
from .store import AndiamoStore
from .windows import active

PROVIDERS = ("tomtom", "ojp")
# The panel hears about new calls at most this often (seconds).
NOTIFY_DELAY = 10


class Usage:
    """Today's calls per provider. Neither provider says when its day resets, so it's UTC midnight."""

    def __init__(self, hass: HomeAssistant, store: AndiamoStore) -> None:
        self.hass = hass
        self.store = store
        self._notify: CALLBACK_TYPE | None = None
        self._planned_for: tuple[Any, dict[str, int]] | None = None

    def _today(self) -> dict[str, Any]:
        day = dt_util.utcnow().date().isoformat()
        if self.store.usage.get("day") != day:
            self.store.usage = {"day": day, **{name: 0 for name in PROVIDERS}}
        return self.store.usage

    @callback
    def count(self, provider: str) -> None:
        today = self._today()
        today[provider] = today.get(provider, 0) + 1
        self.store.delay_save()
        if self._notify is None:
            self._notify = async_call_later(self.hass, NOTIFY_DELAY, self._send)

    @callback
    def _send(self, _now: Any) -> None:
        self._notify = None
        async_dispatcher_send(self.hass, SIGNAL_USAGE_CHANGED)

    def stop(self) -> None:
        if self._notify is not None:
            self._notify()
            self._notify = None

    def as_dict(self) -> dict[str, Any]:
        today = self._today()
        settings = self.store.settings
        planned = self.planned(dt_util.now().date())
        return {
            name: {
                "calls": today.get(name, 0),
                "planned": planned[name],
                "limit": settings[f"limit_{name}"],
            }
            for name in PROVIDERS
        }

    def planned(self, day: date) -> dict[str, int]:
        """The calls the watchdog and the departure sensors make on `day`, from their windows.

        Countdowns, checks, searches and open cards depend on what people do, so
        only the count of today's calls includes them.
        """
        key = (day, repr(self.store.routes), repr(self.store.stations))
        if self._planned_for and self._planned_for[0] == key:
            return self._planned_for[1]
        zone = dt_util.get_default_time_zone()
        start = datetime.combine(day, time(), tzinfo=zone)
        minutes = [start + timedelta(minutes=m) for m in range(24 * 60)]
        watch_every = WATCH_INTERVAL.total_seconds() / 60
        calls = {name: 0.0 for name in PROVIDERS}
        # {stop_ref: [shortest interval of the routes due that minute, or None]}
        boards: dict[str, list[float | None]] = {}
        for route in self.store.routes:
            if route.get("watch_windows"):
                provider = "tomtom" if route["mode"] == MODE_CAR else "ojp"
                watched = sum(1 for m in minutes if active(route["watch_windows"], m))
                calls[provider] += watched / watch_every
            if route["mode"] == MODE_TRANSIT and route.get("departure_windows") and route.get("lines"):
                try:
                    stop_ref = self.store.route_station(route)["stop_ref"]
                except Exception:  # noqa: BLE001 - no station yet: nothing is fetched
                    continue
                due = boards.setdefault(stop_ref, [None] * len(minutes))
                for i, m in enumerate(minutes):
                    if window := active(route["departure_windows"], m):
                        every = float(window.get("every") or 1)
                        due[i] = every if due[i] is None else min(due[i], every)
        # Routes boarding at the same station share their calls.
        for due in boards.values():
            calls["ojp"] += sum(1 / every for every in due if every)
        result = {name: round(value) for name, value in calls.items()}
        self._planned_for = (key, result)
        return result
