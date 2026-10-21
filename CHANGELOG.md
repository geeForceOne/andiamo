# Changelog

## 0.4.0 - 2026-10-21

### New

- Car routes can be checked now: a car-and-clock button in the panel and the card, a check button entity and the `andiamo.check` action tell you the drive time and traffic delay right now, on the speaker and in a new drive time sensor. The message can be changed in Settings.
- The card has an editor with all its options, so it no longer needs YAML: which routes to show, whether to show the date next to "Arrive by", and for the timetable how many departures and how often to refresh.
- New timetable view for the card: the next departures of your public transport routes, with when to leave.
- Departure sensors: in time windows of your choice, a public transport route gets a next departure sensor (short text with "leave in", e.g. for a pixel clock) and a departures sensor with the list.
- The Andiamo page shows today's API calls, planned from your setup and actually used, against the free daily limits, which can be changed in Settings.
- Routes can have several watch and departure sensor windows, e.g. weekdays 06:30–08:00 and weekends 09:00–11:00, each with its own alert limit, or its own update interval and number of departures. Windows of a route can't overlap. Existing windows carry over.
- Minor changes and updates.

## 0.3.0 - 2026-10-19

### New

- A route can be watched on chosen days and times. Its new problem sensor turns on when traffic, a delay or a cancellation reaches the route's "Alert when late by" limit (default 15 minutes).
- "Announce on" (Speaker, Notification or Off) replaces test mode; each route can choose its own. Test mode turned on becomes Notification.
- The leave-at sensor keeps the last announcement in its `message` attribute, also after "go now".

## 0.2.0 - 2026-10-18

### New

- Car routes have a date next to "arrive by", filled in with today and typed like the time (19.10, 19.10.2026, tomorrow).
- Each route can announce on its own speaker; the one in Settings stays the default.
- New `andiamo.start` and `andiamo.stop` actions start and stop any route from automations, with time, date and a speaker for that run.

### Improved

- Minor fixes and updates.

## 0.1.0 - 2026-10-18

Initial release.
