#!/usr/bin/env bash
set -euo pipefail

HOST="${1:-cal-5.62}"
LOCAL_JSON="/tmp/cal_wasabi_keys.json"

python3 - <<'PY'
import getpass
import json
import pathlib

key = getpass.getpass("Wasabi Access Key ID: ").strip()
secret = getpass.getpass("Wasabi Secret Access Key: ").strip()

if len(key) < 16 or any(c.isspace() for c in key):
    raise SystemExit("Bad key: spaces or too short")
if len(secret) < 32 or any(c.isspace() for c in secret):
    raise SystemExit("Bad secret: spaces or too short")

path = pathlib.Path("/tmp/cal_wasabi_keys.json")
path.write_text(json.dumps({
    "WASABI_KEY_ID": key,
    "WASABI_SECRET": secret,
    "WASABI_BUCKET": "mfsa-cal",
    "WASABI_REGION": "us-east-1",
    "WASABI_ENDPOINT": "https://s3.wasabisys.com",
}))
path.chmod(0o600)
print("Wrote temporary key bundle.")
PY

scp "$LOCAL_JSON" "$HOST:/tmp/cal_wasabi_keys.json"
rm -f "$LOCAL_JSON"

ssh "$HOST" 'python3 - <<'"'"'PY'"'"'
import json
import os
from datetime import datetime, UTC
from pathlib import Path

payload_path = Path("/tmp/cal_wasabi_keys.json")
payload = json.loads(payload_path.read_text())
payload_path.unlink(missing_ok=True)

env = Path("/opt/cal/.env")
backup = Path(f"/opt/cal/.env.before-wasabi-{datetime.now(UTC):%Y%m%d%H%M%S}")
backup.write_text(env.read_text())

lines = env.read_text().splitlines()
out = []
seen = set()

for line in lines:
    if "=" in line and not line.lstrip().startswith("#"):
        key, _ = line.split("=", 1)
        if key in payload:
            out.append(f"{key}={payload[key]}")
            seen.add(key)
        else:
            out.append(line)
    else:
        out.append(line)

for key, value in payload.items():
    if key not in seen:
        out.append(f"{key}={value}")

tmp = env.with_name(".env.tmp-wasabi")
tmp.write_text("\n".join(out) + "\n")
os.chmod(tmp, 0o664)
tmp.replace(env)
print("Updated /opt/cal/.env; backup:", backup)
PY'

ssh "$HOST" 'pkill -f "uvicorn app.main:app" || true; cd /opt/cal && nohup /usr/local/bin/uvicorn app.main:app --host 0.0.0.0 --port 3005 --workers 2 >/tmp/cal-api.log 2>&1 & sleep 3; curl -fsS http://127.0.0.1:3005/health'
