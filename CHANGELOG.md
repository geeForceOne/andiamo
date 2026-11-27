# Changelog

## 1.4.0 - 2026-11-27

### New

- Car routes name the main road and where a jam is: a small "via A4 · jam on A3" line under the drive time in the panel and card, "über die A4 … Stau auf der A3" in the announcement, and on the traffic problem warning. The drive time sensor has new `via` and `jam_road` attributes, and message templates take `{via}` and `{jam}`. This uses no extra TomTom calls.

## 1.3.0 - 2026-11-19

### New

- Settings "Transit reminders" and "Car reminders": choose how many minutes before leaving the reminders start and how often they repeat until "go now". The defaults keep the old behavior (transit: once, 2 min before; car: from 30 min, every 5). Set transit to 0 for no reminder.

### Fixed

- HACS no longer warns that the integration has no categories: it now lists under public transport and cars.

## 1.2.0 - 2026-11-18

### New

- Next: a running public transport route skips to the following departure, from the panel, the card or the new `andiamo.next` action, and announces the new time.
- Card timetable option "Show departures you can't reach on foot": the ones leaving sooner than your walk to the station show grayed out as "too late".

### Changed

- Pressing a route's button entity while the route runs now goes to the next departure instead of stopping it. Stop with the `andiamo.stop` action.

### Fixed

- On phones, the Settings dropdowns (e.g. Speaker) no longer run past the edge of the screen.
- A tram or train running early shows "1 min early" instead of a red "+-1 min"; the timetable view shows it too.

## 1.1.0 - 2026-10-25

### New

- Sort routes and places on the Andiamo page by dragging them.
- The card's timetable view also shows car routes: the drive time if you leave now, the distance, a traffic jam if there is one, and the ETA.
- Car routes in the panel and the card show an ETA next to the drive time.
- The card shows its routes in the order you pick them; drag them in the card editor to change it.

### Fixed

- Minor fixes and updates.

## 1.0.0 - 2026-10-25

### New

- Andiamo is now in the default HACS list: search for Andiamo in HACS and download it, no custom repository needed.

### Fixed

- The Andiamo card shows up on phones again. On some browsers it went missing and the dashboard showed an error in its place.

## 0.4.1 - 2026-10-22

### Changed

- On a phone, the route list on the Andiamo page is compact: one line per route with Start on the right, "Arrive by" and the date only after tapping Start, and Delete inside the route's edit form.

### Fixed

- Adding the Andiamo card to a dashboard no longer gets stuck on a spinning wheel.

## 0.4.0 - 2026-10-21

### New

- Car routes can be checked now: a car-and-clock button in the panel and the card, a check button entity and the `andiamo.check` action tell you the drive time and traffic delay right now, on the speaker and in a new drive time sensor. The message can be changed in Settings.
- The card has an editor with all its options, so it no longer needs YAML: which routes to show, whether to show the date next to "Arrive by", and for the timetable how many departures and how often to refresh.
- New timetable view for the card: the next departures of your public transport routes, with when to leave.
- Departure sensors: in time windows of your choice, a public transport route gets a next departure sensor (short text with "leave in", e.g. for a pixel clock) and a departures sensor with the list.
- The Andiamo page shows today's API calls, planned from your setup and actually used, against the free daily limits, which can be changed in Settings.
- Routes can have several watch and departure sensor windows, e.g. weekdays 06:30–08:00 and weekends 09:00–11:00, each with its own alert limit, or its own update interval and number of departures. Windows of a route can't overlap. Existing windows carry over.
- Car routes can plan a reserve on top of the drive time, e.g. 10 minutes for parking: in Settings for all car routes, or per route.
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
