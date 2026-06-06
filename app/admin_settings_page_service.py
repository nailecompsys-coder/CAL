from __future__ import annotations

from sqlalchemy.orm import Session

from . import wasabi_backup
from .models import Surgeon, SurgeonDevice


def settings_backups(request) -> list[dict]:
    backups = wasabi_backup.list_backups() if wasabi_backup.is_configured() else []
    backup_ts = request.query_params.get("ts", "").strip()
    if backup_ts and request.query_params.get("msg") == "backup_ok":
        key = f"{wasabi_backup.BACKUP_PREFIX}{backup_ts}/db.sql.gz"
        new_entry = {"timestamp": backup_ts, "files": [{"name": "db.sql.gz", "key": key}], "total_bytes": 0}
        existing_ts = {backup["timestamp"] for backup in backups}
        if backup_ts not in existing_ts:
            backups = [new_entry] + backups
    return backups


def registered_surgeon_devices(db: Session) -> list[SurgeonDevice]:
    return (
        db.query(SurgeonDevice)
        .join(Surgeon)
        .order_by(Surgeon.last_name, Surgeon.first_name, SurgeonDevice.registered_at.desc())
        .all()
    )


def rules_engine_settings(db: Session) -> tuple[dict, list]:
    from .rules_engine.engine import get_rule_config
    from .rules_engine.registry import ALL_RULES as _ALL_RULES

    return get_rule_config(db), list(_ALL_RULES) if _ALL_RULES else []
