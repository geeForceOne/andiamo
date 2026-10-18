# Changelog

## 0.1.0 (unreleased)

- First version: places with stations and walking times, public transport routes (opentransportdata.swiss, real time) and car routes (TomTom, live traffic).
- Public transport routes take the lines you tick, picked from the lines leaving the station; only those count.
- Routes show a train, bus or tram icon depending on the lines they take.
- Station search shows what stops at each result (train, tram, bus...), so a train station is easy to tell from the tram stop outside it.
- One button per public transport route: says when to leave, "2 minutes left" and "go now"; follows delays and switches to another ticked line when that one now leaves first; pressing again cancels.
- Car routes: set "arrive by" on the dashboard card; countdown every 5 minutes from 30 minutes before leaving; announces traffic changes.
- Sidebar page for places, stations, routes and settings; test mode shows announcements as notifications.
- Announcements use the text-to-speech voice for the chosen language (Swiss German when your HA is set to Switzerland and the engine has it); Echo speakers from Alexa Media Player speak in Alexa's own voice, no text-to-speech engine needed.
- Times follow your Home Assistant profile's time format (12 or 24 hours); "Arrive by" takes a typed time like 18:30, 1830 or 6:30 pm.
- After an update, browsers load the new Andiamo page and card by themselves, no cache clearing needed.
- Your own announcement texts in Settings, per language, with placeholders like {time}, {line} and {departure}; empty means the built-in text.
- Ready for HACS: MIT license, HACS and Hassfest checks on GitHub, and a button in the README that opens Andiamo in HACS. The README says where it works: car routes anywhere, public transport in Switzerland for now.
