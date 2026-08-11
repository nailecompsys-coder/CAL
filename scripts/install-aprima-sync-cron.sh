#!/usr/bin/env bash
# Hourly Aprima → CAL cache sync (read-only against Aprima).
# Runs inside cal_api so DATABASE_URL + APRIMA_CONNECTION_STRING are set.
#
# Schedule: :05 every hour America/New_York (exceeds daily minimum)
# Install:  CONFIRM=1 ./scripts/install-aprima-sync-cron.sh
#
# Runner script is tracked in git (scripts/run-aprima-sync-cron.sh).
# Install only ensures it is executable and installs the crontab line —
# it does NOT regenerate the runner from a heredoc (that left cron broken
# after rsync/deploys wiped the untracked file ~Jul 23).
#
# Prod host: cal-prod-vm (192.168.5.62), app path /opt/cal

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
APP_ROOT="${CAL_APP_ROOT:-/opt/cal}"
LOG_FILE="${CAL_APRIMA_SYNC_LOG:-/var/log/cal-aprima-sync.log}"
CRON_TAG="# cal-aprima-sync"
CONTAINER="${CAL_API_CONTAINER:-cal_api}"
RUNNER="${APP_ROOT}/scripts/run-aprima-sync-cron.sh"
SOURCE_RUNNER="${SCRIPT_DIR}/run-aprima-sync-cron.sh"

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

if [[ ! -f "${SOURCE_RUNNER}" ]]; then
  echo "ERROR: tracked runner missing: ${SOURCE_RUNNER}" >&2
  echo "  Restore scripts/run-aprima-sync-cron.sh from git — do not regenerate via heredoc." >&2
  exit 1
fi

mkdir -p "${APP_ROOT}/scripts"
if [[ "$(cd "$(dirname "${SOURCE_RUNNER}")" && pwd)/$(basename "${SOURCE_RUNNER}")" != \
      "$(cd "$(dirname "${RUNNER}")" 2>/dev/null && pwd)/$(basename "${RUNNER}")" ]]; then
  # Install from a different checkout path into APP_ROOT (e.g. Mac → /opt/cal).
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

echo "Installed. Current crontab entries for Aprima sync:"
crontab -l | grep "${CRON_TAG}" || true
echo
echo "Seed once (no push spam), then normal hourly runs notify on change:"
echo "  CAL_APRIMA_SYNC_ARGS='--no-notify' ${RUNNER}"
echo "  ${RUNNER}"
