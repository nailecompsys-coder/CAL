#!/usr/bin/env bash
# Hourly Aprima → CAL cache sync (read-only against Aprima).
# Runs inside cal_api so DATABASE_URL + APRIMA_CONNECTION_STRING are set.
#
# Schedule: :05 every hour America/New_York
# Install:  CONFIRM=1 ./scripts/install-aprima-sync-cron.sh
#
# Prod host: cal-prod-vm (192.168.5.62), app path /opt/cal

set -euo pipefail

APP_ROOT="${CAL_APP_ROOT:-/opt/cal}"
LOG_FILE="${CAL_APRIMA_SYNC_LOG:-/var/log/cal-aprima-sync.log}"
CRON_TAG="# cal-aprima-sync"
CONTAINER="${CAL_API_CONTAINER:-cal_api}"
RUNNER="${APP_ROOT}/scripts/run-aprima-sync-cron.sh"

# :05 past each hour — after top-of-hour clinic edits settle.
CRON_LINE="5 * * * * TZ=America/New_York ${RUNNER} >> ${LOG_FILE} 2>&1 ${CRON_TAG}"

echo "CAL Aprima hourly sync cron"
echo "  app root  : ${APP_ROOT}"
echo "  container : ${CONTAINER}"
echo "  runner    : ${RUNNER}"
echo "  log file  : ${LOG_FILE}"
echo "  schedule  : :05 every hour America/New_York"
echo
echo "Cron line:"
echo "  ${CRON_LINE}"
echo

if [[ "${CONFIRM:-}" != "1" ]]; then
  echo "Dry print only. To install into the current user crontab:"
  echo "  CONFIRM=1 CAL_APP_ROOT=${APP_ROOT} $0"
  echo
  echo "One-shot seed (no push spam):"
  echo "  CAL_APRIMA_SYNC_ARGS='--no-notify' ${RUNNER}"
  exit 0
fi

if [[ ! -d "${APP_ROOT}/server" ]]; then
  echo "ERROR: ${APP_ROOT}/server not found. Set CAL_APP_ROOT to the CAL checkout." >&2
  exit 1
fi

mkdir -p "${APP_ROOT}/scripts"
# Host runner: docker exec into cal_api (image only COPYs app/, not server/scripts).
cat > "${RUNNER}" <<'RUNNER'
#!/usr/bin/env bash
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
RUNNER
chmod +x "${RUNNER}"

if [[ ! -f "${LOG_FILE}" ]]; then
  if sudo -n touch "${LOG_FILE}" 2>/dev/null; then
    sudo -n chown "$(whoami)" "${LOG_FILE}" 2>/dev/null || true
  else
    touch "${LOG_FILE}" 2>/dev/null || true
  fi
fi

EXISTING="$(crontab -l 2>/dev/null || true)"
FILTERED="$(printf '%s\n' "${EXISTING}" | grep -v "${CRON_TAG}" || true)"
{
  printf '%s\n' "${FILTERED}"
  printf '%s\n' "${CRON_LINE}"
} | crontab -

echo "Installed. Current crontab entries for Aprima sync:"
crontab -l | grep "${CRON_TAG}" || true
echo
echo "Seed once (no push spam), then normal hourly runs notify on change:"
echo "  CAL_APRIMA_SYNC_ARGS='--no-notify' ${RUNNER}"
echo "  ${RUNNER}"
