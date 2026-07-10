#!/usr/bin/env bash
# Install (or print) the CAL scheduler daily digest cron on the host.
#
# Default: print the cron line only (safe).
# Install: CONFIRM=1 ./scripts/install-scheduler-digest-cron.sh
#
# Target: daily 06:00 America/New_York → server/scripts/send_scheduler_digest.py
# Prod host: cal-prod-vm (192.168.5.62), app path /opt/cal

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
APP_ROOT="${CAL_APP_ROOT:-/opt/cal}"
PYTHON_BIN="${CAL_PYTHON:-python3}"
LOG_FILE="${CAL_DIGEST_LOG:-/var/log/cal-scheduler-digest.log}"
CRON_TAG="# cal-scheduler-digest"

CRON_LINE="0 6 * * * cd ${APP_ROOT}/server && TZ=America/New_York PYTHONPATH=. ${PYTHON_BIN} scripts/send_scheduler_digest.py >> ${LOG_FILE} 2>&1 ${CRON_TAG}"

echo "CAL scheduler digest cron"
echo "  app root : ${APP_ROOT}"
echo "  python   : ${PYTHON_BIN}"
echo "  log file : ${LOG_FILE}"
echo "  schedule : 06:00 America/New_York daily"
echo
echo "Cron line:"
echo "  ${CRON_LINE}"
echo

if [[ "${CONFIRM:-}" != "1" ]]; then
  echo "Dry print only. To install into the current user crontab:"
  echo "  CONFIRM=1 CAL_APP_ROOT=${APP_ROOT} $0"
  echo
  echo "Dry-run the job first:"
  echo "  cd ${APP_ROOT}/server && PYTHONPATH=. ${PYTHON_BIN} scripts/send_scheduler_digest.py --dry-run"
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

echo "Installed. Current crontab entries for CAL digest:"
crontab -l | grep "${CRON_TAG}" || true
echo
echo "Verify with a dry-run, then a one-shot send when SMTP is ready:"
echo "  cd ${APP_ROOT}/server && PYTHONPATH=. ${PYTHON_BIN} scripts/send_scheduler_digest.py --dry-run"
echo "  cd ${APP_ROOT}/server && PYTHONPATH=. ${PYTHON_BIN} scripts/send_scheduler_digest.py"
