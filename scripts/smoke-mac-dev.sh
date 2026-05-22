#!/usr/bin/env bash
set -euo pipefail

BASE_URL="${CAL_BASE_URL:-http://127.0.0.1:3005}"

echo "== CAL smoke checks =="
echo "[1/3] /health"
curl -sf "$BASE_URL/health" | python3 -m json.tool

echo "[2/3] /api/health"
curl -sf "$BASE_URL/api/health" | python3 -m json.tool

echo "[3/3] Header check"
curl -sI "$BASE_URL/health" | tr -d '\r' | awk 'BEGIN{IGNORECASE=1}/^x-app-version:/{print}'

echo "Smoke checks passed."
