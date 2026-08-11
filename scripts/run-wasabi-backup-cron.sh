#!/usr/bin/env bash
# Host runner for daily Wasabi backup.
# Invoked by cron; docker-execs into cal_api.
# Tracked in git so deploys/rsync cannot leave cron pointing at a missing file.
set -euo pipefail

CONTAINER="${CAL_API_CONTAINER:-cal_api}"

if docker ps >/dev/null 2>&1; then
  DOCKER=(docker)
else
  DOCKER=(sudo docker)
fi

if ! "${DOCKER[@]}" ps --format '{{.Names}}' | grep -qx "${CONTAINER}"; then
  echo "ERROR: container ${CONTAINER} is not running" >&2
  exit 1
fi

"${DOCKER[@]}" exec -w /app -e PYTHONPATH=/app "${CONTAINER}" \
  python -c 'from app.wasabi_backup import run_backup; import json,sys; r=run_backup(); print(json.dumps(r, indent=2, default=str)); sys.exit(0 if r.get("success") and r.get("wasabi_ok", True) else 1)'
