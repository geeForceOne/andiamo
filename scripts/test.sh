#!/usr/bin/env bash
# Runs the tests in WSL: wsl -d Ubuntu -- bash scripts/test.sh [pytest args]
set -euo pipefail
cd "$(dirname "$0")/.."
source ~/.venvs/andiamo/bin/activate
timeout "${TEST_TIMEOUT:-120}" python -m pytest -q -p no:cacheprovider "$@"
