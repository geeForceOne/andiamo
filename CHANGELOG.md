# Changelog

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
