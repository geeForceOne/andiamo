"""Constants for Andiamo."""

from __future__ import annotations

from datetime import timedelta
from typing import Final

DOMAIN: Final = "andiamo"

CONF_OJP_KEY: Final = "ojp_api_key"
CONF_TOMTOM_KEY: Final = "tomtom_api_key"

STORAGE_KEY: Final = DOMAIN
STORAGE_VERSION: Final = 1

PANEL_URL_PATH: Final = DOMAIN
PANEL_COMPONENT: Final = "andiamo-panel"
STATIC_URL: Final = f"/{DOMAIN}_static"

EVENT_ANNOUNCEMENT: Final = f"{DOMAIN}_announcement"
SIGNAL_RUNS_CHANGED: Final = f"{DOMAIN}_runs_changed"
SIGNAL_DATA_CHANGED: Final = f"{DOMAIN}_data_changed"

MODE_TRANSIT: Final = "transit"
MODE_CAR: Final = "car"

DEFAULT_LANGUAGE: Final = "de"
LANGUAGES: Final = ("de", "en")
DEFAULT_CAR_LEAD_MINUTES: Final = 30

# Public transport: fixed reminder before "go now".
TRANSIT_REMINDER: Final = timedelta(minutes=2)
# Car: countdown step between announcements.
CAR_STEP_MINUTES: Final = 5
# A changed leave time is only announced from this difference on.
CAR_CHANGE_THRESHOLD: Final = timedelta(minutes=2)
TRANSIT_CHANGE_THRESHOLD: Final = timedelta(minutes=1)

# How often an active run asks the provider again.
TRANSIT_RECHECK: Final = timedelta(minutes=1)
CAR_RECHECK_NEAR: Final = timedelta(minutes=2)
CAR_RECHECK_FAR: Final = timedelta(minutes=15)
