#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  scripts/dr-restore-from-wasabi.sh cal-backups/YYYYMMDD-HHMMSS

Purpose:
  Rebuild/restore CAL from Git + a Wasabi database backup on a prepared server.

Required before running:
  - Docker and Docker Compose plugin installed
  - CAL repo cloned or pulled
  - Production .env present in repo root with valid secrets
  - WASABI_* env values in .env

This script restores the database into the standalone Docker stack. It does not
restore nginx, DNS, SSL certificates, or secrets.
EOF
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" || $# -ne 1 ]]; then
  usage
  exit $([[ $# -eq 1 ]] && echo 0 || echo 2)
fi

BACKUP_PREFIX="${1%/}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ENV_FILE="${ROOT}/.env"
TMP_DIR="$(mktemp -d -t cal-dr-restore.XXXXXX)"
trap 'rm -rf "$TMP_DIR"' EXIT

cd "$ROOT"

if [[ ! -f "$ENV_FILE" ]]; then
  echo "Missing ${ENV_FILE}. Restore requires production secrets/config." >&2
  exit 1
fi

python3 - "$ENV_FILE" >"${TMP_DIR}/env.sh" <<'PY'
import shlex
import sys
from pathlib import Path

for raw in Path(sys.argv[1]).read_text().splitlines():
    line = raw.strip()
    if not line or line.startswith("#") or "=" not in line:
        continue
    key, value = line.split("=", 1)
    key = key.strip()
    if not key:
        continue
    print(f"export {key}={shlex.quote(value.strip())}")
PY
set -a
# shellcheck disable=SC1090
source "${TMP_DIR}/env.sh"
set +a

for key in WASABI_BUCKET WASABI_KEY_ID WASABI_SECRET DATABASE_URL CAL_DB_NAME CAL_DB_USER CAL_DB_PASSWORD; do
  if [[ -z "${!key:-}" ]]; then
    echo "Missing ${key} in .env" >&2
    exit 1
  fi
done

if ! command -v docker >/dev/null 2>&1; then
  echo "docker is required" >&2
  exit 1
fi

DOCKER=(docker)
if ! docker ps >/dev/null 2>&1; then
  DOCKER=(sudo -n docker)
fi

COMPOSE=("${DOCKER[@]}" compose -f docker-compose.standalone.yml)

echo "==> Fetching backup metadata from Wasabi"
python3 - "$BACKUP_PREFIX" "$TMP_DIR" <<'PY'
import os
import sys

import boto3
from botocore.config import Config

prefix = sys.argv[1].rstrip("/")
tmp_dir = sys.argv[2]
bucket = os.environ["WASABI_BUCKET"]
region = os.environ.get("WASABI_REGION", "us-east-1")
endpoint = os.environ.get("WASABI_ENDPOINT") or f"https://s3.{region}.wasabisys.com"
if not endpoint.startswith(("http://", "https://")):
    endpoint = "https://" + endpoint

client = boto3.client(
    "s3",
    endpoint_url=endpoint.rstrip("/"),
    region_name=region,
    aws_access_key_id=os.environ["WASABI_KEY_ID"],
    aws_secret_access_key=os.environ["WASABI_SECRET"],
    config=Config(signature_version="s3v4"),
)

db_key = f"{prefix}/db.sql.gz"
manifest_key = f"{prefix}/manifest.json"
client.download_file(bucket, db_key, f"{tmp_dir}/db.sql.gz")
try:
    client.download_file(bucket, manifest_key, f"{tmp_dir}/manifest.json")
except Exception:
    pass
head = client.head_object(Bucket=bucket, Key=db_key)
print(f"downloaded={db_key} size={head.get('ContentLength')}")
PY

if [[ -f "${TMP_DIR}/manifest.json" ]]; then
  echo "==> Manifest"
  python3 -m json.tool "${TMP_DIR}/manifest.json" || true
fi

echo "==> Pulling latest Git code"
git pull --ff-only || {
  echo "Git pull failed. Resolve repository state before DR restore." >&2
  exit 1
}

echo "==> Starting standalone Postgres"
"${COMPOSE[@]}" up -d cal_postgres
for _ in {1..30}; do
  if "${DOCKER[@]}" exec cal_postgres pg_isready -U "$CAL_DB_USER" -d "$CAL_DB_NAME" >/dev/null 2>&1; then
    break
  fi
  sleep 2
done

echo "==> Restoring database from backup"
gunzip -c "${TMP_DIR}/db.sql.gz" | "${DOCKER[@]}" exec -i \
  -e "PGPASSWORD=${CAL_DB_PASSWORD}" \
  cal_postgres psql -U "$CAL_DB_USER" -d "$CAL_DB_NAME" --no-password

echo "==> Building and starting CAL API"
CAL_APP_VERSION="$(tr -d '[:space:]' < VERSION)" "${COMPOSE[@]}" build cal_api
CAL_APP_VERSION="$(tr -d '[:space:]' < VERSION)" "${COMPOSE[@]}" up -d --no-build cal_api

echo "==> Waiting for health"
for _ in {1..30}; do
  if curl -fsS http://127.0.0.1:3005/health >/dev/null 2>&1; then
    curl -fsS http://127.0.0.1:3005/health
    echo
    echo "DR restore complete."
    exit 0
  fi
  sleep 2
done

echo "CAL API did not become healthy. Check docker logs cal_api." >&2
exit 1
