#!/usr/bin/env bash
# Install (or print) the hourly Aprima → CAL cache sync cron.
#
# Default: print the cron line only (safe).
# Install: CONFIRM=1 ./scripts/install-aprima-sync-cron.sh
#
# Target: every hour at :05 America/New_York → server/scripts/sync_aprima.py
# Prod host: cal-prod-vm (192.168.5.62), app path /opt/cal
#
# Requires APRIMA_CONNECTION_STRING in the API/.env used by the host Python
# process (same read-only Aprima account as the portal).

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
APP_ROOT="${CAL_APP_ROOT:-/opt/cal}"
PYTHON_BIN="${CAL_PYTHON:-python3}"
LOG_FILE="${CAL_APRIMA_SYNC_LOG:-/var/log/cal-aprima-sync.log}"
CRON_TAG="# cal-aprima-sync"

# :05 past each hour — after top-of-hour clinic edits settle.
CRON_LINE="5 * * * * cd ${APP_ROOT}/server && TZ=America/New_York PYTHONPATH=. ${PYTHON_BIN} scripts/sync_aprima.py >> ${LOG_FILE} 2>&1 ${CRON_TAG}"

echo "CAL Aprima hourly sync cron"
echo "  app root : ${APP_ROOT}"
echo "  python   : ${PYTHON_BIN}"
echo "  log file : ${LOG_FILE}"
echo "  schedule : :05 every hour America/New_York"
echo
echo "Cron line:"
echo "  ${CRON_LINE}"
echo

if [[ "${CONFIRM:-}" != "1" ]]; then
  echo "Dry print only. To install into the current user crontab:"
  echo "  CONFIRM=1 CAL_APP_ROOT=${APP_ROOT} $0"
  echo
  echo "Dry-run status first:"
  echo "  cd ${APP_ROOT}/server && PYTHONPATH=. ${PYTHON_BIN} scripts/sync_aprima.py --dry-run"
  echo "One-shot sync (no push spam during first seed):"
  echo "  cd ${APP_ROOT}/server && PYTHONPATH=. ${PYTHON_BIN} scripts/sync_aprima.py --no-notify"
  exit 0
fi

if [[ ! -d "${APP_ROOT}/server" ]]; then
  echo "ERROR: ${APP_ROOT}/server not found. Set CAL_APP_ROOT to the CAL checkout." >&2
  exit 1
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
echo "Verify:"
echo "  cd ${APP_ROOT}/server && PYTHONPATH=. ${PYTHON_BIN} scripts/sync_aprima.py --dry-run"
echo "  cd ${APP_ROOT}/server && PYTHONPATH=. ${PYTHON_BIN} scripts/sync_aprima.py --no-notify"
