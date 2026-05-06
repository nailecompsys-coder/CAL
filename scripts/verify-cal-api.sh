#!/usr/bin/env bash
# Fail if the process listening on :3005 is not running repo root VERSION (no rebuild).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
EXPECTED="$(tr -d '[:space:]' < "$ROOT/VERSION")"
URL="${CAL_HEALTH_URL:-http://127.0.0.1:3005/health}"

if ! command -v curl >/dev/null; then
  echo "curl required" >&2
  exit 1
fi

BODY="$(curl -sf "$URL" 2>/dev/null)" || {
  echo "ERROR: no response from $URL (is cal_api up on this host?)" >&2
  exit 1
}

ACTUAL="$(printf '%s' "$BODY" | python3 -c "import sys, json; print(str(json.load(sys.stdin).get('version', '')).strip())" 2>/dev/null || true)"
if [[ -z "$ACTUAL" ]]; then
  echo "ERROR: could not parse version from /health JSON" >&2
  exit 1
fi

if [[ "$ACTUAL" != "$EXPECTED" ]]; then
  echo "ERROR: running API version='$ACTUAL' but repo VERSION='$EXPECTED'" >&2
  echo "Fix: run ./scripts/rebuild-cal-api.sh on the host that serves $URL" >&2
  echo "     If you use another compose file with image: ...:oldtag, remove it or retag." >&2
  exit 1
fi

HDR="$(curl -sfI "$URL" | tr -d '\r' | grep -i '^x-app-version:' || true)"
echo "OK  /health version=$ACTUAL  $HDR"
