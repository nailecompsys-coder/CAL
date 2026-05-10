#!/usr/bin/env bash
# Rebuild and restart cal_api so the running container matches this repo.
# By default: bumps VERSION (new build badge), syncs sw.js cache name, then builds.
#   NO_BUMP=1 ./scripts/rebuild-cal-api.sh   — rebuild without changing VERSION
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [[ "${NO_BUMP:-}" != "1" ]]; then
  echo "==> Bump VERSION (unique build id)"
  "$ROOT/scripts/bump-version.sh"
  "$ROOT/scripts/sync-sw-cache-name.sh"
else
  echo "==> NO_BUMP=1 — leaving VERSION and sw.js unchanged"
fi

export CAL_APP_VERSION="$(tr -d '[:space:]' < "$ROOT/VERSION")"
EXPECTED="$CAL_APP_VERSION"

echo "==> Repo VERSION: $EXPECTED"
echo "==> Stop/remove old container and local tag (avoids BuildKit 'image already exists' on cal_api:local)"
docker compose stop cal_api 2>/dev/null || true
docker compose rm -f cal_api 2>/dev/null || true
docker rmi -f cal_api:local 2>/dev/null || true

use_standalone() {
  [[ "${CAL_STANDALONE:-}" == "1" ]] && return 0
  if ! docker network inspect atlas-net >/dev/null 2>&1; then return 0; fi
  if ! docker network inspect atlas_default >/dev/null 2>&1; then return 0; fi
  return 1
}

echo "==> Building cal_api from $ROOT"
# Layer cache is safe to use: docker rmi above already removed the cal_api:local tag,
# which eliminates the BuildKit stale-tag problem. apt and pip layers are reused when
# Dockerfile/requirements.txt are unchanged (code-only changes rebuild in ~15-30s).
if use_standalone; then
  echo "==> Using docker-compose.standalone.yml (atlas networks missing or CAL_STANDALONE=1)."
  echo "==> This path brings up both cal_postgres and cal_api on the standalone VM."
  docker compose -f docker-compose.standalone.yml stop cal_api 2>/dev/null || true
  docker compose -f docker-compose.standalone.yml rm -f cal_api 2>/dev/null || true
  docker rmi -f cal_api:local 2>/dev/null || true
  docker compose -f docker-compose.standalone.yml up -d cal_postgres
  docker compose -f docker-compose.standalone.yml build cal_api
  docker compose -f docker-compose.standalone.yml up -d --no-build cal_api
else
  docker compose build cal_api
  echo "==> Starting cal_api (docker-compose.yml + atlas networks)"
  docker compose up -d --no-build cal_api
fi

echo "==> Waiting for /health …"
for i in 1 2 3 4 5 6 7 8 9 10 11 12 15 20; do
  if curl -sf "http://127.0.0.1:3005/health" >/dev/null 2>&1; then
    break
  fi
  sleep 1
done

echo "==> /health"
curl -sf "http://127.0.0.1:3005/health" | python3 -m json.tool || {
  echo "Health check failed — is the container bound to 127.0.0.1:3005?" >&2
  exit 1
}

echo "==> Verify VERSION matches running container"
if ! "$ROOT/scripts/verify-cal-api.sh"; then
  echo "Hint: docker ps | grep cal_api  — confirm the image is cal_api:local and not an old tag." >&2
  exit 1
fi

echo "Done. Surgeon PWA footer should show: Build $EXPECTED"
