#!/usr/bin/env bash
# Host runner for Aprima → CAL cache sync.
# Invoked by cron; docker-execs into cal_api (image has app/, not server/scripts).
# Tracked in git so deploys/rsync cannot leave cron pointing at a missing file.
#
# Optional: CAL_APRIMA_SYNC_ARGS='--no-notify' | '--dry-run' | '--days-ahead N'
set -euo pipefail

CONTAINER="${CAL_API_CONTAINER:-cal_api}"
ARGS="${CAL_APRIMA_SYNC_ARGS:-}"

if docker ps >/dev/null 2>&1; then
  DOCKER=(docker)
else
  DOCKER=(sudo docker)
fi

if ! "${DOCKER[@]}" ps --format '{{.Names}}' | grep -qx "${CONTAINER}"; then
  echo "ERROR: container ${CONTAINER} is not running" >&2
  exit 1
fi

"${DOCKER[@]}" exec -w /app -e PYTHONPATH=/app -e CAL_APRIMA_SYNC_ARGS="${ARGS}" "${CONTAINER}" \
  python -c '
import json, os, sys
from app.aprima_cache_service import run_aprima_sync, sync_status_payload
from app.database import SessionLocal
extra = os.environ.get("CAL_APRIMA_SYNC_ARGS", "").split()
dry_run = "--dry-run" in extra
no_notify = "--no-notify" in extra
days_ahead = 21
if "--days-ahead" in extra:
    i = extra.index("--days-ahead")
    if i + 1 < len(extra):
        days_ahead = int(extra[i + 1])
db = SessionLocal()
try:
    if dry_run:
        print(json.dumps(sync_status_payload(db), indent=2, default=str))
        sys.exit(0)
    result = run_aprima_sync(db, days_ahead=days_ahead, notify=not no_notify)
    print(json.dumps(result, indent=2, default=str))
    sys.exit(0 if result.get("ok") else 1)
finally:
    db.close()
'
