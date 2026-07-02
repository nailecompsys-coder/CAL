#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
REPO_ROOT="$(cd "$ROOT/.." && pwd)"
cd "$ROOT"

if ! command -v docker >/dev/null 2>&1; then
  echo "ERROR: docker not found. Install Docker Desktop first." >&2
  exit 1
fi

if [[ ! -f "$REPO_ROOT/.env.mac-dev" ]]; then
  cp "$REPO_ROOT/.env.mac-dev.example" "$REPO_ROOT/.env.mac-dev"
  echo "Created .env.mac-dev from template. Update secrets before real testing."
fi

export CAL_APP_VERSION="$(tr -d '[:space:]' < "$ROOT/VERSION" 2>/dev/null || echo mac-dev)"
export CAL_GIT_COMMIT="$(git -C "$REPO_ROOT" rev-parse HEAD 2>/dev/null || echo unknown)"
export CAL_GIT_BRANCH="$(git -C "$REPO_ROOT" rev-parse --abbrev-ref HEAD 2>/dev/null || echo unknown)"
export CAL_GIT_REMOTE="$(git -C "$REPO_ROOT" remote get-url origin 2>/dev/null || echo unknown)"
export COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME:-cal}"

echo "Starting CAL mac dev stack..."
docker compose --env-file "$REPO_ROOT/.env.mac-dev" -f docker-compose.mac-dev.yml up -d --build

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
