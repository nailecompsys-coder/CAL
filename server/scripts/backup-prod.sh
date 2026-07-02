#!/usr/bin/env bash
set -euo pipefail

TIMESTAMP="$(date +%Y%m%d-%H%M%S)"
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REPO_ROOT="$(cd "${ROOT_DIR}/.." && pwd)"
ENV_FILE="${REPO_ROOT}/.env"
BACKUP_DIR="${HOME}/cal-backups/${TIMESTAMP}"
WASABI_DEST="${CAL_WASABI_DEST:-wasabi:mfsa-cal/cal-backups/${TIMESTAMP}}"

if [[ "${EUID}" -ne 0 ]] && ! docker ps >/dev/null 2>&1; then
  echo "Docker is not accessible as $(whoami); re-running backup with sudo ..."
  exec sudo -E "$0" "$@"
fi

mkdir -p "${BACKUP_DIR}"
export CAL_REPO_ROOT="${REPO_ROOT}"

if [[ ! -f "${ENV_FILE}" ]]; then
  echo "Missing .env at ${ENV_FILE}"
  exit 1
fi

while IFS= read -r raw_line || [[ -n "$raw_line" ]]; do
  line="${raw_line#"${raw_line%%[![:space:]]*}"}"
  [[ -z "$line" || "${line:0:1}" == "#" ]] && continue
  key="${line%%=*}"
  value="${line#*=}"
  key="${key%"${key##*[![:space:]]}"}"
  value="${value#"${value%%[![:space:]]*}"}"
  if [[ -n "$key" ]]; then
    export "$key=$value"
  fi
done < "${ENV_FILE}"

if [[ -z "${DATABASE_URL:-}" ]]; then
  echo "DATABASE_URL is not set in ${ENV_FILE}"
  exit 1
fi

if ! command -v python3 >/dev/null 2>&1; then
  echo "python3 is required to parse DATABASE_URL"
  exit 1
fi

readarray -t DB_PARTS < <(
  python3 - <<'PY'
import os
from urllib.parse import urlparse

url = os.environ["DATABASE_URL"]
if url.startswith("postgres://"):
    url = "postgresql://" + url[len("postgres://"):]
r = urlparse(url)
print(r.hostname or "127.0.0.1")
print(r.port or 5432)
print(r.username or "")
print(r.password or "")
print((r.path or "").lstrip("/").split("?", 1)[0] or "surgical_cal")
PY
)

DB_HOST="${DB_PARTS[0]}"
DB_PORT="${DB_PARTS[1]}"
DB_USER="${DB_PARTS[2]}"
DB_PASSWORD="${DB_PARTS[3]}"
DB_NAME="${DB_PARTS[4]}"

cat > "${BACKUP_DIR}/metadata.txt" <<EOF
timestamp=${TIMESTAMP}
app=cal
database_name=${DB_NAME}
database_host=${DB_HOST}
database_port=${DB_PORT}
EOF

python3 - "${BACKUP_DIR}/manifest.json" "${TIMESTAMP}" <<'PY'
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

manifest_path = Path(sys.argv[1])
timestamp = sys.argv[2]
repo = Path(os.environ["CAL_REPO_ROOT"])

def git_value(args):
    try:
        return subprocess.check_output(["git", "-C", str(repo), *args], text=True, stderr=subprocess.DEVNULL).strip() or None
    except Exception:
        return None

def version():
    try:
        return (repo / "server" / "VERSION").read_text().strip() or None
    except Exception:
        return None

safe_keys = [
    "BASE_URL",
    "CAL_BIND_HOST",
    "CAL_DB_NAME",
    "CAL_DB_USER",
    "WASABI_BUCKET",
    "WASABI_REGION",
    "WASABI_ENDPOINT",
]
secret_keys = [
    "APRIMA_CONNECTION_STRING",
    "CAL_DB_PASSWORD",
    "DATABASE_URL",
    "SECRET_KEY",
    "VAPID_PRIVATE_KEY",
    "VAPID_PUBLIC_KEY",
    "VAPID_EMAIL",
    "WASABI_KEY_ID",
    "WASABI_SECRET",
]

manifest = {
    "app": "CAL",
    "backup_type": "database-plus-manifest",
    "created_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    "timestamp": timestamp,
    "app_version": version(),
    "git": {
        "remote": os.environ.get("CAL_GIT_REMOTE") or git_value(["remote", "get-url", "origin"]),
        "commit": os.environ.get("CAL_GIT_COMMIT") or git_value(["rev-parse", "HEAD"]),
        "branch": os.environ.get("CAL_GIT_BRANCH") or git_value(["rev-parse", "--abbrev-ref", "HEAD"]),
        "dirty": False if os.environ.get("CAL_GIT_COMMIT") else bool(git_value(["status", "--porcelain"])),
    },
    "database": {
        "engine": "postgresql",
        "dump_key": f"cal-backups/{timestamp}/db.sql.gz",
        "dump_file": "db.sql.gz",
    },
    "restore": {
        "code_source": "git",
        "minimum_files_required": ["db.sql.gz", "manifest.json", ".env"],
        "script": "server/scripts/dr-restore-from-wasabi.sh",
    },
    "env": {
        "safe_values": {key: os.environ[key] for key in safe_keys if os.environ.get(key)},
        "present_secret_keys": sorted(key for key in secret_keys if os.environ.get(key)),
        "missing_secret_keys": sorted(key for key in secret_keys if not os.environ.get(key)),
        "note": "Secrets are not stored in this backup. Restore requires a valid production .env.",
    },
}
manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
PY

echo "Creating CAL database dump ..."
if docker ps -a --format '{{.Names}}' | grep -q '^cal_postgres$'; then
  docker exec -e PGPASSWORD="${DB_PASSWORD}" cal_postgres \
    pg_dump -U "${DB_USER}" "${DB_NAME}" \
    | gzip > "${BACKUP_DIR}/db.sql.gz"
else
  PGPASSWORD="${DB_PASSWORD}" pg_dump \
    -h "${DB_HOST}" \
    -p "${DB_PORT}" \
    -U "${DB_USER}" \
    "${DB_NAME}" \
    | gzip > "${BACKUP_DIR}/db.sql.gz"
fi
echo "  OK: ${BACKUP_DIR}/db.sql.gz"

echo "Saving git-tracked files snapshot ..."
git -C "${REPO_ROOT}" archive --format=tar.gz \
  -o "${BACKUP_DIR}/repo-tracked.tar.gz" HEAD
echo "  OK: ${BACKUP_DIR}/repo-tracked.tar.gz"

echo "Uploading to Wasabi (${WASABI_DEST}) ..."
if ! command -v rclone >/dev/null 2>&1; then
  echo "  SKIP: rclone not installed - files kept locally only"
else
  rclone copy "${BACKUP_DIR}" "${WASABI_DEST}" \
    --progress \
    --transfers 4 \
    --s3-upload-cutoff 50M \
    --s3-chunk-size 10M
  echo "  OK: uploaded to ${WASABI_DEST}"

  rm -rf "${BACKUP_DIR}"
  echo "  OK: local copy removed"
fi

echo
echo "Backup complete - ${TIMESTAMP}"
echo "  Wasabi: ${WASABI_DEST}"
