"""Run a CAL database backup to Wasabi (pg_dump → gzip → S3).

Usage (inside cal_api container):
  PYTHONPATH=/app python /app/scripts/run_wasabi_backup.py
  PYTHONPATH=/app python -c "from app.wasabi_backup import run_backup; print(run_backup())"
"""

from __future__ import annotations

import json
import sys


def main() -> int:
    from app.wasabi_backup import is_configured, run_backup

    if not is_configured():
        print(json.dumps({"success": False, "error": "Wasabi credentials not configured"}))
        return 1
    result = run_backup()
    print(json.dumps(result, indent=2, default=str))
    return 0 if result.get("success") and result.get("wasabi_ok", True) else 1


if __name__ == "__main__":
    sys.exit(main())
