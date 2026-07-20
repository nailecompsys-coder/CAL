from __future__ import annotations

from sqlalchemy import case
from sqlalchemy.orm import Session

from . import wasabi_backup
from .models import AdminNotification, Surgeon, SurgeonDevice, SurgeonOtpAuditLog


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


def recent_otp_audit_logs(db: Session, limit: int = 50) -> list[SurgeonOtpAuditLog]:
    return (
        db.query(SurgeonOtpAuditLog)
        .outerjoin(Surgeon, Surgeon.id == SurgeonOtpAuditLog.surgeon_id)
        .order_by(SurgeonOtpAuditLog.created_at.desc(), SurgeonOtpAuditLog.id.desc())
        .limit(limit)
        .all()
    )


def _dayoff_id_from_notification(row: AdminNotification) -> int | None:
    import json

    try:
        data = json.loads(row.payload or "{}")
    except (TypeError, ValueError):
        return None
    raw = data.get("dayOffId")
    if raw is None:
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def reconcile_stale_dayoff_notifications(db: Session, admin_user_id: int | None = None) -> int:
    """Remove day_off_request notifications once the DayOff is no longer pending.

    Marking them read still left "Pending Request" cards on the dashboard.
    Handled requests should disappear from the feed entirely.
    """
    from .models import DayOff

    q = db.query(AdminNotification).filter(AdminNotification.kind == "day_off_request")
    if admin_user_id is not None:
        q = q.filter(AdminNotification.admin_user_id == admin_user_id)
    rows = q.all()
    removed = 0
    for row in rows:
        dayoff_id = _dayoff_id_from_notification(row)
        if dayoff_id is None:
            db.delete(row)
            removed += 1
            continue
        dayoff = db.get(DayOff, dayoff_id)
        if dayoff is None or (dayoff.status or "") != "pending":
            db.delete(row)
            removed += 1
    if removed:
        db.commit()
    return removed


def recent_admin_notifications(db: Session, admin_user_id: int, limit: int = 20) -> list[AdminNotification]:
    """FIFO: oldest entered first (top-left → right → down). Unread before read.

    Day-off request cards only appear while the underlying DayOff is still pending.
    Duplicate notify spam (one row per admin fan-out) is collapsed to one card per dayOffId.
    """
    reconcile_stale_dayoff_notifications(db, admin_user_id)
    rows = (
        db.query(AdminNotification)
        .filter(AdminNotification.admin_user_id == admin_user_id)
        .order_by(
            case((AdminNotification.read_at.is_(None), 0), else_=1),
            AdminNotification.created_at.asc().nullsfirst(),
            AdminNotification.id.asc(),
        )
        .limit(max(limit * 5, limit))
        .all()
    )
    rows = sorted(
        rows,
        key=lambda row: (
            1 if row.read_at is not None else 0,
            row.created_at or row.id or 0,
            row.id or 0,
        ),
    )
    seen_dayoff: set[int] = set()
    visible: list[AdminNotification] = []
    for row in rows:
        if row.kind == "day_off_request":
            dayoff_id = _dayoff_id_from_notification(row)
            if dayoff_id is not None:
                if dayoff_id in seen_dayoff:
                    continue
                seen_dayoff.add(dayoff_id)
        visible.append(row)
        if len(visible) >= limit:
            break
    return visible


def unread_admin_notification_count(db: Session, admin_user_id: int) -> int:
    reconcile_stale_dayoff_notifications(db, admin_user_id)
    # Count distinct pending day-off requests + other unread kinds.
    rows = (
        db.query(AdminNotification)
        .filter(
            AdminNotification.admin_user_id == admin_user_id,
            AdminNotification.read_at.is_(None),
        )
        .all()
    )
    seen_dayoff: set[int] = set()
    count = 0
    for row in rows:
        if row.kind == "day_off_request":
            dayoff_id = _dayoff_id_from_notification(row)
            if dayoff_id is not None:
                if dayoff_id in seen_dayoff:
                    continue
                seen_dayoff.add(dayoff_id)
        count += 1
    return count


def rules_engine_settings(db: Session) -> tuple[dict, list]:
    from .rules_engine.engine import get_rule_config
    from .rules_engine.registry import ALL_RULES as _ALL_RULES

    return get_rule_config(db), list(_ALL_RULES) if _ALL_RULES else []
