#!/usr/bin/env bash
# Restore a production-parity dump into the LOCAL Mac-dev Postgres only.
# Never points at production. Never runs without CONFIRM=1.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"

DUMP_PATH="${1:-$ROOT/cal_live.dump}"
CONFIRM="${CONFIRM:-}"
DB_CONTAINER="${CAL_DB_CONTAINER:-cal_db}"
DB_NAME="${CAL_DB_NAME:-surgical_cal}"
DB_USER="${CAL_DB_USER:-cal_user}"

if [[ "$CONFIRM" != "1" ]]; then
  cat >&2 <<EOF
Refusing to wipe local database without CONFIRM=1.

This replaces ALL data in the local Docker DB ($DB_CONTAINER / $DB_NAME)
with the dump file. It does NOT touch production.

Usage:
  CONFIRM=1 ./server/scripts/restore-mac-dev-dump.sh
  CONFIRM=1 ./server/scripts/restore-mac-dev-dump.sh /path/to/cal_live.dump

Current default dump: $DUMP_PATH
EOF
  exit 2
fi

if [[ ! -f "$DUMP_PATH" ]]; then
  echo "ERROR: dump not found: $DUMP_PATH" >&2
  echo "Place a pg_dump custom-format file at repo root as cal_live.dump, or pass a path." >&2
  exit 1
fi

if ! docker inspect "$DB_CONTAINER" >/dev/null 2>&1; then
  echo "ERROR: container $DB_CONTAINER is not running. Start local stack first:" >&2
  echo "  make mac-dev-up" >&2
  exit 1
fi

# Safety: only allow restore into containers that look like local Mac-dev.
CONTAINER_IMAGE="$(docker inspect -f '{{.Config.Image}}' "$DB_CONTAINER")"
case "$CONTAINER_IMAGE" in
  postgres:*|postgres) ;;
  *)
    echo "ERROR: refusing restore into unexpected image: $CONTAINER_IMAGE" >&2
    exit 1
    ;;
esac

# Refuse if DATABASE_URL in the running API points off-box (extra belt).
if docker inspect cal_api >/dev/null 2>&1; then
  API_DB_URL="$(docker exec cal_api printenv DATABASE_URL 2>/dev/null || true)"
  if [[ -n "$API_DB_URL" ]] && ! printf '%s' "$API_DB_URL" | grep -Eq '@(cal_db|localhost|127\.0\.0\.1)(:|/|$)'; then
    echo "ERROR: cal_api DATABASE_URL does not look local: refusing restore." >&2
    echo "  $API_DB_URL" >&2
    exit 1
  fi
fi

echo "Restoring $DUMP_PATH into local $DB_CONTAINER:$DB_NAME ..."
echo "This DROPS and recreates the local database, then loads the dump."

# Load password from .env.mac-dev when present (local only).
if [[ -f "$ROOT/.env.mac-dev" ]]; then
  # shellcheck disable=SC1091
  set -a
  # shellcheck disable=SC1090
  source <(grep -E '^(CAL_DB_PASSWORD|CAL_DB_USER|CAL_DB_NAME)=' "$ROOT/.env.mac-dev" | sed 's/\r$//')
  set +a
fi
DB_PASSWORD="${CAL_DB_PASSWORD:-cal_local_dev_change_me}"
DB_USER="${CAL_DB_USER:-$DB_USER}"
DB_NAME="${CAL_DB_NAME:-$DB_NAME}"

NETWORK="$(docker inspect -f '{{range $k,$v := .NetworkSettings.Networks}}{{$k}}{{end}}' "$DB_CONTAINER")"
if [[ -z "$NETWORK" ]]; then
  echo "ERROR: could not resolve Docker network for $DB_CONTAINER" >&2
  exit 1
fi

# Stop API so it is not holding connections during DROP DATABASE.
if docker inspect cal_api >/dev/null 2>&1; then
  echo "Stopping cal_api for clean restore..."
  docker stop cal_api >/dev/null
fi

echo "Recreating empty local database $DB_NAME ..."
docker exec "$DB_CONTAINER" psql -U "$DB_USER" -d postgres -v ON_ERROR_STOP=1 -c \
  "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = '$DB_NAME' AND pid <> pg_backend_pid();" >/dev/null
docker exec "$DB_CONTAINER" psql -U "$DB_USER" -d postgres -v ON_ERROR_STOP=1 -c \
  "DROP DATABASE IF EXISTS \"$DB_NAME\";"
docker exec "$DB_CONTAINER" psql -U "$DB_USER" -d postgres -v ON_ERROR_STOP=1 -c \
  "CREATE DATABASE \"$DB_NAME\" OWNER \"$DB_USER\";"

# Custom-format dump (PGDMP) needs a pg_restore new enough for archive v1.16+.
# Local cal_db is Postgres 16; use a Postgres 17 client container against cal_db.
# Ignore harmless SET transaction_timeout errors from newer dump headers.
if file "$DUMP_PATH" | grep -qi 'PostgreSQL custom database dump'; then
  DUMP_ABS="$(cd "$(dirname "$DUMP_PATH")" && pwd)/$(basename "$DUMP_PATH")"
  set +e
  docker run --rm \
    --network "$NETWORK" \
    -e PGPASSWORD="$DB_PASSWORD" \
    -v "$DUMP_ABS:/dump.dump:ro" \
    postgres:17-alpine \
    pg_restore \
      --no-owner --no-acl \
      -h "$DB_CONTAINER" -U "$DB_USER" -d "$DB_NAME" \
      /dump.dump 2> >(grep -v 'transaction_timeout' >&2)
  RESTORE_RC=$?
  set -e
  # pg_restore returns 1 when only ignorable warnings occurred.
  if [[ "$RESTORE_RC" -gt 1 ]]; then
    echo "ERROR: pg_restore failed with exit $RESTORE_RC" >&2
    exit "$RESTORE_RC"
  fi
else
  FILTERED="$(mktemp -t cal-sql-XXXXXX.sql)"
  grep -Ev '^\\(restrict|unrestrict) ' "$DUMP_PATH" > "$FILTERED" || cp "$DUMP_PATH" "$FILTERED"
  docker exec -i -e PGPASSWORD="$DB_PASSWORD" "$DB_CONTAINER" \
    psql -U "$DB_USER" -d "$DB_NAME" --quiet < "$FILTERED"
  rm -f "$FILTERED"
fi

echo "Starting cal_api..."
docker start cal_api >/dev/null
for _ in $(seq 1 30); do
  if curl -sf "http://127.0.0.1:3005/health" >/dev/null 2>&1; then
    break
  fi
  sleep 2
done

echo
echo "Restore finished. Row counts:"
docker exec "$DB_CONTAINER" psql -U "$DB_USER" -d "$DB_NAME" -c \
  "SELECT
     (SELECT COUNT(*) FROM surgeons) AS surgeons,
     (SELECT COUNT(*) FROM locations) AS locations,
     (SELECT COUNT(*) FROM admin_users) AS admins,
     (SELECT COUNT(*) FROM or_block_instances) AS or_blocks;"

echo
echo "Next:"
echo "  1. Portal:  http://127.0.0.1:3005/admin/login"
echo "  2. Sim DEBUG builds already call http://127.0.0.1:3005"
echo "  3. Local OTP bypass (mac-dev compose): scheduler 654321; set CAL_LOCAL_DEV_SURGEON_OTP similarly for surgeons"
echo "  4. make mac-dev-smoke"
echo
echo "If admin password from the dump is unknown, reset LOCAL admin only:"
echo "  docker exec -it cal_api python -c \"from app.database import SessionLocal; from app.models import AdminUser; from app.auth import hash_password; db=SessionLocal(); a=db.query(AdminUser).filter_by(username='admin').first(); a.password_hash=hash_password('LocalDev2026!'); db.commit(); print('local admin password set')\""
