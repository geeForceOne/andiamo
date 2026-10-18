<img src="custom_components/andiamo/brand/icon.png" alt="" width="96" align="right">

# Andiamo

[![Open your Home Assistant instance and open Andiamo in HACS.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=geeForceOne&repository=andiamo&category=integration)

**Never miss your train, bus or tram again, and stop checking the time while you get ready.**

Andiamo (Italian for *"let's go!"*) is a Home Assistant integration that tells you, out loud on your speaker, exactly when to leave the house: to catch your bus, tram or train, or to arrive somewhere by car on time.

- **Public transport (Switzerland):** press one button and your speaker says *"You need to leave at 10:15, that is in 7 minutes."*, then *"2 minutes left"* and *"Go now!"*. Andiamo knows how long you walk to your stop and which lines you take, follows real-time delays, and announces a new time if yours moves. Too late for the next train, bus or tram? It quietly picks the one after. Press again to cancel.
- **Car:** set "arrive by 19:00" on the dashboard card. From 30 minutes before you need to leave, the speaker counts down every 5 minutes (*"You have 25 minutes left"*) and ends with *"Go now!"*. Live traffic is followed all the way, so a jam on the way means an earlier "go".

Everything is set up on one sidebar page, no YAML. Announcements are in German (default) or English.

**Where it works:** car routes work anywhere TomTom has maps. Public transport uses Swiss data (opentransportdata.swiss), so it only covers Switzerland for now. Other free transport data providers can be added: [open an issue](https://github.com/geeForceOne/andiamo/issues) and say which one you'd like.

## Screenshots

**Routes:** one tap to start; a running route shows when to leave and which tram it catches.

![Routes tab with a running route](docs/screenshots/routes.png)

**Places and stations:** each place has its stations with the walking time; the search shows what stops there, so the train station is easy to tell from the tram stop outside.

![Places tab with stations and a station search](docs/screenshots/places.png)

**Settings:** speaker, language and your own announcement texts.

![Settings tab with the message templates](docs/screenshots/settings.png)

**Dashboard card:** start routes and set "arrive by" for the car.

<img src="docs/screenshots/card.png" alt="Andiamo dashboard card" width="420">

## What you need

- Home Assistant 2026.3 or newer.
- For public transport: a free API key from [opentransportdata.swiss](https://api-manager.opentransportdata.swiss/) (OJP 2.0).
- For the car: a free API key from [TomTom](https://developer.tomtom.com/) (Routing and Search).
- A text-to-speech entity (e.g. Google Translate, Piper) and a speaker (`media_player`).

## Install

**HACS:** use the button at the top, or HACS → ⋮ → Custom repositories → add `https://github.com/geeForceOne/andiamo` as *Integration*, install **Andiamo**, restart Home Assistant.

**By hand:** copy `custom_components/andiamo` into your `/config/custom_components/` folder and restart.

Then: Settings → Devices & services → Add integration → **Andiamo**, and enter one or both API keys. Change the keys later with **Reconfigure** on the integration.

## Set up

Open **Andiamo** in the sidebar.

1. **Places:** your home is there already as the main place. Add more places (e.g. *Office*, *Climbing gym*) by address search or coordinates.
2. **Stations:** under a place, search for a stop and set how many minutes you walk there. The first one is the main station; any station can be made main.
3. **Routes:** a public transport route boards at a station (the main one unless you pick another) and takes the lines you tick, e.g. *10 → Zürich Flughafen*; the form lists the lines leaving that station. A car route goes from one place to another, e.g. *Home → Climbing gym*.
4. **Settings:** text-to-speech entity, speaker, language, when the car countdown starts, and **test mode** (announcements appear as notifications instead of on the speaker).

## Use

- Each public transport route gets a button entity, e.g. `button.andiamo_home_office`. Press it from a dashboard, or from a physical button with an automation:

  ```yaml
  triggers:
    - trigger: state
      entity_id: event.hallway_button_action
  actions:
    - action: button.press
      target:
        entity_id: button.andiamo_home_office
  ```

- Add the **Andiamo** card to a dashboard (`type: custom:andiamo-card`, optional `mode: car` or `transit`, `routes: [Home → Office]`, `title:`). It starts routes and sets "arrive by" for car routes.
- Each route has a sensor (`sensor.andiamo_…`) with the leave time while a countdown runs.
- Every announcement is also fired as the event `andiamo_announcement` (with `route` and `message`), e.g. to send it to your phone too.

## Development

Tests run in Linux (WSL on Windows):

```bash
uv venv --python 3.14 ~/.venvs/andiamo
source ~/.venvs/andiamo/bin/activate
uv pip install -r requirements_test.txt
bash scripts/test.sh
```

## License

[MIT](LICENSE)
