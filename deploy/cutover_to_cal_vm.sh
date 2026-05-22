#!/usr/bin/env bash
set -euo pipefail

TARGET_VM="${1:-192.168.5.62}"
TARGET_URL="http://${TARGET_VM}:3005"
NGINX_CONF="/etc/nginx/sites-available/cal.midfloridasurgical.com.conf"
BACKUP_ROOT="/root/cal-cutover-backups"
STAMP="$(date +%Y%m%d-%H%M%S)"
BACKUP_DIR="${BACKUP_ROOT}/${STAMP}"

if [[ ! -f "${NGINX_CONF}" ]]; then
  echo "Missing nginx config: ${NGINX_CONF}" >&2
  exit 1
fi

echo "Checking target health at ${TARGET_URL}/health ..."
curl -sf "${TARGET_URL}/health" >/dev/null

mkdir -p "${BACKUP_DIR}"
cp "${NGINX_CONF}" "${BACKUP_DIR}/cal.midfloridasurgical.com.conf"

python3 - <<PY
from pathlib import Path
import re

path = Path("${NGINX_CONF}")
text = path.read_text()
new = "proxy_pass ${TARGET_URL}/;"

pattern = re.compile(r"proxy_pass\\s+(?:http|https)://(?:127\\.0\\.0\\.1:3005|192\\.168\\.5\\.75|192\\.168\\.5\\.62)(?:/)?;")
if new in text:
    print("CAL nginx already points at ${TARGET_URL}")
elif pattern.search(text):
    text = pattern.sub(new, text, count=1)
    path.write_text(text)
    print("Updated CAL nginx upstream to ${TARGET_URL}")
else:
    raise SystemExit("Expected CAL upstream line not found")
PY

nginx -t
systemctl reload nginx

echo "Cutover complete."
echo "Backup saved to ${BACKUP_DIR}"
