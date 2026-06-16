#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if ! command -v docker >/dev/null 2>&1; then
  echo "ERROR: docker not found. Install Docker Desktop first." >&2
  exit 1
fi

if [[ ! -f "$ROOT/.env.mac-dev" ]]; then
  cp "$ROOT/.env.mac-dev.example" "$ROOT/.env.mac-dev"
  echo "Created .env.mac-dev from template. Update secrets before real testing."
fi

export CAL_APP_VERSION="$(tr -d '[:space:]' < "$ROOT/VERSION" 2>/dev/null || echo mac-dev)"
export CAL_GIT_COMMIT="$(git -C "$ROOT" rev-parse HEAD 2>/dev/null || echo unknown)"
export CAL_GIT_BRANCH="$(git -C "$ROOT" rev-parse --abbrev-ref HEAD 2>/dev/null || echo unknown)"
export CAL_GIT_REMOTE="$(git -C "$ROOT" remote get-url origin 2>/dev/null || echo unknown)"

echo "Starting CAL mac dev stack..."
docker compose -f docker-compose.mac-dev.yml up -d --build

echo "Waiting for health endpoint..."
for _ in $(seq 1 30); do
  if curl -sf "http://127.0.0.1:3005/health" >/dev/null 2>&1; then
    break
  fi
  sleep 2
done

echo "Health response:"
curl -sf "http://127.0.0.1:3005/health" | python3 -m json.tool

echo "Done. Open http://127.0.0.1:3005/"
