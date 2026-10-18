#!/usr/bin/env bash
# Starts a throwaway Home Assistant with Andiamo linked in, on port 8123.
#   wsl -d Ubuntu -- bash scripts/dev-ha.sh
# Config lives in ~/andiamo-dev (Linux side, never your real HA); remove it to start over.
set -euo pipefail
repo="$(cd "$(dirname "$0")/.." && pwd)"
config="$HOME/andiamo-dev"

mkdir -p "$config/custom_components"
ln -sfn "$repo/custom_components/andiamo" "$config/custom_components/andiamo"

if [ ! -f "$config/configuration.yaml" ]; then
  cat > "$config/configuration.yaml" <<'YAML'
homeassistant:
  name: Test Home
  latitude: 47.3769
  longitude: 8.5417
  elevation: 400
  unit_system: metric
  time_zone: Europe/Zurich
  country: CH
  currency: CHF

frontend:
config:
onboarding:
history:
logbook:

logger:
  default: warning
  logs:
    custom_components.andiamo: debug
YAML
fi

source ~/.venvs/andiamo-ha/bin/activate
exec hass -c "$config"
