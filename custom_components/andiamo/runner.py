"""Countdowns: when to leave, reminders and "go now" on the speaker."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta
import logging
from typing import Any

from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import async_track_point_in_utc_time
from homeassistant.util import dt as dt_util

from .announcer import Announcer
from .const import (
    CAR_CHANGE_THRESHOLD,
    CAR_RECHECK_FAR,
    CAR_RECHECK_NEAR,
    CAR_STEP_MINUTES,
    MODE_CAR,
    MODE_TRANSIT,
    SIGNAL_RUNS_CHANGED,
    TRANSIT_CHANGE_THRESHOLD,
    TRANSIT_RECHECK,
    TRANSIT_REMINDER,
)
from .providers import CarProvider, Departure, ProviderError, TransitProvider
from .store import DataError, AndiamoStore
from .texts import clock, minutes, minutes_until, text

_LOGGER = logging.getLogger(__name__)


class RunManager:
    """Holds the countdown of each route that is running."""

    def __init__(
        self,
        hass: HomeAssistant,
        store: AndiamoStore,
        announcer: Announcer,
        transit: Callable[[], TransitProvider],
        car: Callable[[], CarProvider],
    ) -> None:
        self.hass = hass
        self.store = store
        self.announcer = announcer
        self.transit = transit
        self.car = car
        self.runs: dict[str, Run] = {}

    async def async_resume(self) -> None:
        """Pick up car countdowns that were set up before a restart."""
        for route_id, arrive_at in list(self.store.car_runs.items()):
            arrive = dt_util.parse_datetime(arrive_at)
            try:
                route = self.store.route(route_id)
            except DataError:
                route = None
            if route is None or arrive is None or arrive <= dt_util.utcnow():
                self.store.car_runs.pop(route_id)
                continue
            run = CarRun(self, route, arrive)
            self.runs[route_id] = run
            try:
                await run.async_start()
            except (ProviderError, DataError) as err:
                # Keep it; the next check will try again.
                _LOGGER.warning("Can't plan %s yet: %s", route["name"], err)
                run.schedule_recheck(CAR_RECHECK_NEAR)
        await self.store.async_save(notify=False)
        self.changed()

    async def async_press(self, route_id: str) -> None:
        """The route's button: start a public transport countdown, or cancel it."""
        if route_id in self.runs:
            await self.async_cancel(route_id)
            return
        route = self.store.route(route_id)
        if route["mode"] != MODE_TRANSIT:
            raise DataError(f"{route['name']} is a car route; set an arrival time")
        run = TransitRun(self, route)
        self.runs[route_id] = run
        try:
            await run.async_start()
        except Exception:
            self.runs.pop(route_id, None)
            raise
        finally:
            self.changed()

    async def async_start_car(self, route_id: str, arrive_at: datetime) -> None:
        route = self.store.route(route_id)
        if route["mode"] != MODE_CAR:
            raise DataError(f"{route['name']} is not a car route")
        if arrive_at <= dt_util.utcnow():
            raise DataError("The arrival time has already passed")
        if route_id in self.runs:
            await self.async_cancel(route_id, say=False)
        run = CarRun(self, route, dt_util.as_utc(arrive_at))
        await run.async_start()
        if run.finished:
            # Already time to go; "go now" has been said.
            return
        self.runs[route_id] = run
        self.store.car_runs[route_id] = run.arrive_at.isoformat()
        await self.store.async_save(notify=False)
        self.changed()

    async def async_cancel(self, route_id: str, say: bool = True) -> None:
        run = self.runs.pop(route_id, None)
        if run is None:
            return
        run.stop()
        if say and run.announced:
            await run.say(text(run.language, "cancelled"))
        await self.async_forget(run)

    async def async_finished(self, run: Run) -> None:
        if self.runs.get(run.route["id"]) is run:
            del self.runs[run.route["id"]]
        await self.async_forget(run)

    async def async_forget(self, run: Run) -> None:
        if self.store.car_runs.pop(run.route["id"], None) is not None:
            await self.store.async_save(notify=False)
        self.changed()

    def stop_all(self) -> None:
        for run in self.runs.values():
            run.stop()
        self.runs.clear()

    @callback
    def changed(self) -> None:
        async_dispatcher_send(self.hass, SIGNAL_RUNS_CHANGED)

    def as_list(self) -> list[dict[str, Any]]:
        return [run.as_dict() for run in self.runs.values()]


class Run:
    """A countdown to a leave time, with announcements on the way."""

    mode: str

    def __init__(self, manager: RunManager, route: dict[str, Any]) -> None:
        self.manager = manager
        self.hass = manager.hass
        self.route = route
        self.leave_at: datetime | None = None
        self.announced = False
        self._timers: list[CALLBACK_TYPE] = []
        self._recheck: CALLBACK_TYPE | None = None
        self._stopped = False

    @property
    def finished(self) -> bool:
        return self._stopped

    @property
    def language(self) -> str:
        return self.manager.store.settings.get("language", "de")

    async def say(self, message: str) -> None:
        self.announced = True
        speaker = self.manager.store.settings.get("speaker")
        await self.manager.announcer.async_say(message, self.route, speaker)

    def say_leave(self, key: str, now: datetime) -> str:
        assert self.leave_at is not None
        return text(
            self.language,
            key,
            time=clock(self.leave_at),
            minutes=minutes(self.language, minutes_until(self.leave_at, now)),
        )

    def stop(self) -> None:
        self._stopped = True
        self._clear_timers()
        if self._recheck:
            self._recheck()
            self._recheck = None

    def at(self, when: datetime, action: Callable[[], Any]) -> None:
        @callback
        def _fire(_now: datetime) -> None:
            if not self._stopped:
                self.hass.async_create_task(action())

        self._timers.append(async_track_point_in_utc_time(self.hass, _fire, when))

    def schedule_recheck(self, delay: timedelta) -> None:
        if self._recheck:
            self._recheck()

        @callback
        def _fire(_now: datetime) -> None:
            self._recheck = None
            if not self._stopped:
                self.hass.async_create_task(self._async_recheck_safe())

        self._recheck = async_track_point_in_utc_time(
            self.hass, _fire, dt_util.utcnow() + delay
        )

    async def _async_recheck_safe(self) -> None:
        try:
            await self.async_recheck()
        except ProviderError as err:
            _LOGGER.warning("Check for %s failed: %s", self.route["name"], err)
            self.schedule_recheck(self.recheck_interval())
        except Exception:
            _LOGGER.exception("Check for %s failed", self.route["name"])
            self.schedule_recheck(self.recheck_interval())

    async def async_go(self) -> None:
        self.stop()
        await self.say(text(self.language, "go_now"))
        await self.manager.async_finished(self)

    def _clear_timers(self) -> None:
        for unsub in self._timers:
            unsub()
        self._timers.clear()

    async def async_recheck(self) -> None:
        raise NotImplementedError

    def recheck_interval(self) -> timedelta:
        raise NotImplementedError

    def as_dict(self) -> dict[str, Any]:
        return {
            "route_id": self.route["id"],
            "mode": self.mode,
            "leave_at": self.leave_at.isoformat() if self.leave_at else None,
        }


class TransitRun(Run):
    """Catch the next departure on one of the route's lines one can still make."""

    mode = MODE_TRANSIT

    def __init__(self, manager: RunManager, route: dict[str, Any]) -> None:
        super().__init__(manager, route)
        if not route.get("lines"):
            raise DataError(f"Pick a line for {route['name']}")
        self.station = manager.store.route_station(route)
        self.line_keys = {line["key"] for line in route["lines"]}
        self.connection: Departure | None = None

    @property
    def margin(self) -> timedelta:
        """Walking time from the door to the station."""
        return timedelta(minutes=self.station.get("walk_minutes", 0))

    def leave_time(self, departure: Departure) -> datetime:
        return departure.departure - self.margin

    async def _connections(self, earliest: datetime) -> list[Departure]:
        found = await self.manager.transit().departures(self.station["stop_ref"], earliest)
        return [d for d in found if d.line_key in self.line_keys]

    async def async_start(self) -> None:
        now = dt_util.utcnow()
        try:
            found = await self._connections(now + self.margin)
        except ProviderError:
            await self.say(text(self.language, "no_connection", route=self.route["name"]))
            raise
        # Too late for the next one: quietly take the next one we can catch.
        catchable = [c for c in found if self.leave_time(c) >= now]
        if not catchable:
            await self.say(text(self.language, "no_connection", route=self.route["name"]))
            raise DataError(f"No connection found for {self.route['name']}")
        self.connection = catchable[0]
        self.leave_at = self.leave_time(self.connection)
        if minutes_until(self.leave_at, now) == 0:
            await self.async_go()
            return
        await self.say(self.say_leave("leave_at", now))
        self._schedule(now)

    def _schedule(self, now: datetime) -> None:
        assert self.leave_at is not None
        self._clear_timers()
        reminder = self.leave_at - TRANSIT_REMINDER
        if reminder > now + timedelta(seconds=30):
            self.at(
                reminder,
                lambda: self.say(
                    text(
                        self.language,
                        "minutes_left",
                        minutes=minutes(self.language, int(TRANSIT_REMINDER.total_seconds() // 60)),
                    )
                ),
            )
        self.at(self.leave_at, self.async_go)
        self.schedule_recheck(TRANSIT_RECHECK)

    def recheck_interval(self) -> timedelta:
        return TRANSIT_RECHECK

    async def async_recheck(self) -> None:
        """Follow the real-time departure; switch if the connection is gone."""
        assert self.connection is not None and self.leave_at is not None
        now = dt_util.utcnow()
        if self.leave_at <= now:
            return
        found = await self._connections(now)
        same = next(
            (
                c
                for c in found
                if c.planned_departure == self.connection.planned_departure
                and c.line_key == self.connection.line_key
            ),
            None,
        )
        if same is None:
            catchable = [c for c in found if self.leave_time(c) >= now]
            if not catchable:
                self.schedule_recheck(TRANSIT_RECHECK)
                return
            same = catchable[0]
        self.connection = same
        new_leave = self.leave_time(same)
        if abs(new_leave - self.leave_at) < TRANSIT_CHANGE_THRESHOLD:
            self.schedule_recheck(TRANSIT_RECHECK)
            return
        self.leave_at = new_leave
        self.manager.changed()
        if new_leave <= now:
            await self.async_go()
            return
        await self.say(self.say_leave("changed", now))
        self._schedule(now)

    def as_dict(self) -> dict[str, Any]:
        data = super().as_dict()
        if self.connection:
            data.update(
                departure=self.connection.departure.isoformat(),
                delay_minutes=round(self.connection.delay.total_seconds() / 60),
                line=self.connection.line,
                line_destination=self.connection.destination,
                station=self.station["name"],
            )
        return data


class CarRun(Run):
    """Arrive by car at a set time, with a countdown every 5 minutes."""

    mode = MODE_CAR

    def __init__(
        self, manager: RunManager, route: dict[str, Any], arrive_at: datetime
    ) -> None:
        super().__init__(manager, route)
        self.arrive_at = arrive_at
        store = manager.store
        self.origin = store.location(route["origin_id"])
        self.destination = store.location(route["destination_id"])
        # Countdown steps already covered, so none is said twice.
        self._said: set[int] = set()

    @property
    def lead(self) -> timedelta:
        return timedelta(minutes=self.manager.store.settings.get("car_lead_minutes", 30))

    async def _departure(self) -> datetime:
        return await self.manager.car().departure_for_arrival(
            (self.origin["latitude"], self.origin["longitude"]),
            (self.destination["latitude"], self.destination["longitude"]),
            self.arrive_at,
        )

    async def async_start(self) -> None:
        self.leave_at = await self._departure()
        now = dt_util.utcnow()
        if self.leave_at <= now:
            await self.async_go()
            return
        if self.leave_at - self.lead <= now:
            # Already inside the countdown: say the leave time once.
            await self.say_leave_time("leave_at", now)
        self._schedule(now)

    async def say_leave_time(self, key: str, now: datetime) -> None:
        """Say the leave time; the steps it already covers are skipped."""
        assert self.leave_at is not None
        left = minutes_until(self.leave_at, now)
        self._said.update(range(left, int(self.lead.total_seconds() // 60) + 1))
        await self.say(self.say_leave(key, now))

    def _schedule(self, now: datetime) -> None:
        assert self.leave_at is not None
        self._clear_timers()
        lead_minutes = int(self.lead.total_seconds() // 60)
        for left in range(lead_minutes, 0, -CAR_STEP_MINUTES):
            when = self.leave_at - timedelta(minutes=left)
            # A step that is due right now still counts (timers can be redone).
            if left not in self._said and when > now - timedelta(seconds=59):
                self.at(when, self._say_left(left))
        self.at(self.leave_at, self.async_go)
        self.schedule_recheck(self.recheck_interval())

    def _say_left(self, left: int) -> Callable[[], Any]:
        async def say_left() -> None:
            if left in self._said:
                return
            self._said.add(left)
            await self.say(
                text(self.language, "minutes_left", minutes=minutes(self.language, left))
            )

        return say_left

    def recheck_interval(self) -> timedelta:
        if self.leave_at is None:
            return CAR_RECHECK_NEAR
        if self.leave_at - self.lead - CAR_RECHECK_FAR > dt_util.utcnow():
            return CAR_RECHECK_FAR
        return CAR_RECHECK_NEAR

    async def async_recheck(self) -> None:
        """Follow the traffic; announce when the leave time moves 2+ minutes."""
        now = dt_util.utcnow()
        new_leave = await self._departure()
        if self.leave_at is None:
            # The first plan failed at startup; this is the first one.
            self.leave_at = new_leave
            self.manager.changed()
            if new_leave <= now:
                await self.async_go()
            else:
                self._schedule(now)
            return
        if self.leave_at <= now:
            return
        if new_leave == self.leave_at:
            self.schedule_recheck(self.recheck_interval())
            return
        moved = abs(new_leave - self.leave_at) >= CAR_CHANGE_THRESHOLD
        self.leave_at = new_leave
        self.manager.changed()
        if new_leave <= now:
            await self.async_go()
            return
        if moved and self.leave_at - self.lead <= now:
            await self.say_leave_time("traffic_changed", now)
        self._schedule(now)

    def as_dict(self) -> dict[str, Any]:
        data = super().as_dict()
        data["arrive_at"] = self.arrive_at.isoformat()
        return data
