#!/usr/bin/env bash
# Stops the test Home Assistant by the process listening on port 8123.
set -euo pipefail
pid="$(ss -ltnp | grep ':8123 ' | head -1 | sed -E 's/.*pid=([0-9]+).*/\1/' || true)"
if [ -z "$pid" ]; then
  echo "not running"
  exit 0
fi
kill "$pid"
for _ in $(seq 1 30); do
  kill -0 "$pid" 2>/dev/null || { echo "stopped $pid"; exit 0; }
  sleep 1
done
echo "still running: $pid"
exit 1
