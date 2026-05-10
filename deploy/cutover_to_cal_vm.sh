#!/usr/bin/env bash
set -euo pipefail

TARGET_VM="${1:-192.168.5.179}"
NGINX_CONF="/etc/nginx/sites-available/cal.midfloridasurgical.com.conf"
BACKUP_ROOT="/root/cal-cutover-backups"
STAMP="$(date +%Y%m%d-%H%M%S)"
BACKUP_DIR="${BACKUP_ROOT}/${STAMP}"

if [[ ! -f "${NGINX_CONF}" ]]; then
  echo "Missing nginx config: ${NGINX_CONF}" >&2
  exit 1
fi

mkdir -p "${BACKUP_DIR}"
cp "${NGINX_CONF}" "${BACKUP_DIR}/cal.midfloridasurgical.com.conf"

python3 - <<PY
from pathlib import Path

path = Path("${NGINX_CONF}")
text = path.read_text()
old = "proxy_pass         http://127.0.0.1:3005/;"
new = "proxy_pass         http://${TARGET_VM}:3005/;"
if old not in text and new not in text:
    raise SystemExit("Expected CAL upstream line not found")
if new in text:
    print("CAL nginx already points at ${TARGET_VM}")
else:
    path.write_text(text.replace(old, new, 1))
    print("Updated CAL nginx upstream to ${TARGET_VM}:3005")
PY

nginx -t
systemctl reload nginx

echo "Cutover complete."
echo "Backup saved to ${BACKUP_DIR}"
