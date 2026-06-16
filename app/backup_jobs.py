from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

STATUS_PATH = Path(os.environ.get("CAL_BACKUP_STATUS_PATH", "/tmp/cal_backup_status.json"))


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _write_status(status: dict) -> None:
    STATUS_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {**status, "updated_at": _now_iso()}
    fd, tmp_name = tempfile.mkstemp(prefix="cal_backup_status_", suffix=".json", dir=str(STATUS_PATH.parent))
    try:
        with os.fdopen(fd, "w") as handle:
            json.dump(payload, handle)
        os.replace(tmp_name, STATUS_PATH)
    finally:
        if os.path.exists(tmp_name):
            os.remove(tmp_name)


def backup_status() -> dict:
    try:
        with STATUS_PATH.open() as handle:
            return json.load(handle)
    except Exception:
        return {"state": "idle"}


def backup_is_running() -> bool:
    return backup_status().get("state") == "running"


def start_backup_job(username: str) -> bool:
    if backup_is_running():
        return False
    _write_status({
        "state": "running",
        "started_at": _now_iso(),
        "started_by": username,
        "message": "Backup is running.",
    })
    return True


def run_backup_job(username: str) -> None:
    try:
        from . import wasabi_backup

        result = wasabi_backup.run_backup()
        if result.get("success") and result.get("wasabi_ok"):
            _write_status({
                "state": "succeeded",
                "started_by": username,
                "finished_at": _now_iso(),
                "timestamp": result.get("timestamp"),
                "wasabi_key": result.get("wasabi_key"),
                "db_size_bytes": result.get("db_size_bytes"),
                "message": "Backup completed and uploaded to Wasabi.",
            })
            return
        if result.get("success") and not result.get("wasabi_ok"):
            _write_status({
                "state": "upload_failed",
                "started_by": username,
                "finished_at": _now_iso(),
                "timestamp": result.get("timestamp"),
                "wasabi_key": result.get("wasabi_key"),
                "error": result.get("wasabi_error", "Wasabi upload failed."),
                "message": "Database dump completed but Wasabi upload failed.",
            })
            return
        _write_status({
            "state": "failed",
            "started_by": username,
            "finished_at": _now_iso(),
            "error": result.get("error", "Backup failed."),
            "message": "Backup failed.",
        })
    except Exception as exc:
        _write_status({
            "state": "failed",
            "started_by": username,
            "finished_at": _now_iso(),
            "error": f"{exc.__class__.__name__}: {exc}",
            "message": "Backup failed.",
        })
