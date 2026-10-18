#!/usr/bin/env bash
# Finishes onboarding of the throwaway test HA (scripts/dev-ha.sh) with user "test"
# and a random password, saved in ~/andiamo-dev/.owner (never your real HA).
set -euo pipefail
base="http://localhost:8123"
client="$base/"
owner="$HOME/andiamo-dev/.owner"

if [ -f "$owner" ]; then
  echo "already onboarded"
  exit 0
fi

password="$(python3 -c 'import secrets; print(secrets.token_urlsafe(18))')"
json() { python3 -c "import json,sys; print(json.load(sys.stdin)[\"$1\"])"; }

code="$(curl -sf -X POST "$base/api/onboarding/users" -H 'Content-Type: application/json' \
  -d "{\"client_id\":\"$client\",\"name\":\"Test\",\"username\":\"test\",\"password\":\"$password\",\"language\":\"en\"}" | json auth_code)"
token="$(curl -sf -X POST "$base/auth/token" \
  -d "grant_type=authorization_code&code=$code&client_id=$client" | json access_token)"

auth=(-H "Authorization: Bearer $token" -H 'Content-Type: application/json')
curl -sf -X POST "$base/api/onboarding/core_config" "${auth[@]}" -d '{}' > /dev/null
curl -sf -X POST "$base/api/onboarding/analytics" "${auth[@]}" -d '{}' > /dev/null
curl -sf -X POST "$base/api/onboarding/integration" "${auth[@]}" \
  -d "{\"client_id\":\"$client\",\"redirect_uri\":\"${base}/?auth_callback=1\"}" > /dev/null

umask 077
printf 'test\n%s\n' "$password" > "$owner"
echo "onboarded: user test, password in $owner"
