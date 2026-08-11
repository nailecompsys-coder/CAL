#!/usr/bin/env bash
# Daily Wasabi backup for CAL (live product).
# Runs inside cal_api so DATABASE_URL + WASABI_* env are already set.
#
# Schedule: 02:00 America/New_York every day
# Install:  CONFIRM=1 ./scripts/install-wasabi-backup-cron.sh
#
# Runner script is tracked in git (scripts/run-wasabi-backup-cron.sh).
# Install only ensures it is executable and installs the crontab line —
# it does NOT regenerate the runner from a heredoc.
#
# Prod host: cal-prod-vm (192.168.5.62), app path /opt/cal

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
APP_ROOT="${CAL_APP_ROOT:-/opt/cal}"
LOG_FILE="${CAL_WASABI_BACKUP_LOG:-/var/log/cal-wasabi-backup.log}"
CRON_TAG="# cal-wasabi-backup"
CONTAINER="${CAL_API_CONTAINER:-cal_api}"
RUNNER="${APP_ROOT}/scripts/run-wasabi-backup-cron.sh"
SOURCE_RUNNER="${SCRIPT_DIR}/run-wasabi-backup-cron.sh"

CRON_LINE="0 2 * * * TZ=America/New_York ${RUNNER} >> ${LOG_FILE} 2>&1 ${CRON_TAG}"

echo "CAL Wasabi daily backup cron"
echo "  app root  : ${APP_ROOT}"
echo "  container : ${CONTAINER}"
echo "  runner    : ${RUNNER}"
echo "  log file  : ${LOG_FILE}"
echo "  schedule  : 02:00 America/New_York daily"
echo
echo "Cron line:"
echo "  ${CRON_LINE}"
echo

if [[ "${CONFIRM:-}" != "1" ]]; then
  echo "Dry print only. To install into the current user crontab:"
  echo "  CONFIRM=1 CAL_APP_ROOT=${APP_ROOT} $0"
  echo
  echo "One-shot test first:"
  echo "  ${RUNNER}"
  exit 0
fi

if [[ ! -d "${APP_ROOT}/server" ]]; then
  echo "ERROR: ${APP_ROOT}/server not found. Set CAL_APP_ROOT to the CAL checkout." >&2
  exit 1
fi

if [[ ! -f "${SOURCE_RUNNER}" ]]; then
  echo "ERROR: tracked runner missing: ${SOURCE_RUNNER}" >&2
  echo "  Restore scripts/run-wasabi-backup-cron.sh from git — do not regenerate via heredoc." >&2
  exit 1
fi

mkdir -p "${APP_ROOT}/scripts"
if [[ "$(cd "$(dirname "${SOURCE_RUNNER}")" && pwd)/$(basename "${SOURCE_RUNNER}")" != \
      "$(cd "$(dirname "${RUNNER}")" 2>/dev/null && pwd)/$(basename "${RUNNER}")" ]]; then
  cp -f "${SOURCE_RUNNER}" "${RUNNER}"
fi
chmod +x "${RUNNER}"

if [[ ! -x "${RUNNER}" ]]; then
  echo "ERROR: runner not executable: ${RUNNER}" >&2
  exit 1
fi

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

echo "Installed. Current crontab entries for Wasabi backup:"
crontab -l | grep "${CRON_TAG}" || true
echo
echo "Verify with a one-shot run:"
echo "  ${RUNNER}"
