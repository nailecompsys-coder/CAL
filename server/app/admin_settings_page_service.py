from __future__ import annotations

import json
from datetime import date

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


def _is_on_call_warning(text: str) -> bool:
    low = (text or "").lower()
    return "surgeon is on call" in low or "assigned on-call" in low or "covering on-call" in low


def _without_on_call_warnings(warnings: list[str] | None) -> list[str]:
    return [row for row in (warnings or []) if not _is_on_call_warning(row)]


def _coerce_flag_date(payload: dict, fallback: date | None = None) -> date | None:
    raw = payload.get("date")
    if raw:
        try:
            return date.fromisoformat(str(raw)[:10])
        except ValueError:
            pass
    return fallback


def _is_past_flag_date(flag_date: date | None) -> bool:
    if flag_date is None:
        return False
    from .scheduling_gate_service import practice_today
    return flag_date < practice_today()


def _schedule_flag_keys(row: AdminNotification) -> tuple[int | None, int | None]:
    import json

    try:
        data = json.loads(row.payload or "{}")
    except (TypeError, ValueError):
        return None, None
    try:
        block_id = int(data["blockId"]) if data.get("blockId") is not None else None
    except (TypeError, ValueError):
        block_id = None
    try:
        surgeon_id = int(data["surgeonId"]) if data.get("surgeonId") is not None else None
    except (TypeError, ValueError):
        surgeon_id = None
    return block_id, surgeon_id


def reconcile_stale_schedule_flag_notifications(
    db: Session,
    admin_user_id: int | None = None,
) -> int:
    """Remove Block OR schedule_flag cards once the conflict is no longer real.

    Fixed ⇒ gone from the dashboard (not left as 'read').
    """
    from .models import ORBlockAssignment, ORBlockInstance
    from .or_block_service import ACTIVE_BLOCK_STATUSES, block_assignment_warnings

    q = db.query(AdminNotification).filter(AdminNotification.kind == "schedule_flag")
    if admin_user_id is not None:
        q = q.filter(AdminNotification.admin_user_id == admin_user_id)
    rows = q.all()
    removed = 0
    for row in rows:
        try:
            payload = json.loads(row.payload or "{}") if row.payload else {}
        except (TypeError, ValueError):
            payload = {}
        if _is_past_flag_date(_coerce_flag_date(payload)):
            db.delete(row)
            removed += 1
            continue
        block_id, surgeon_id = _schedule_flag_keys(row)
        if not block_id:
            db.delete(row)
            removed += 1
            continue
        block = db.get(ORBlockInstance, block_id)
        if block is None or (block.status or "") not in ACTIVE_BLOCK_STATUSES:
            db.delete(row)
            removed += 1
            continue
        if _is_past_flag_date(_coerce_flag_date(payload, block.date)):
            db.delete(row)
            removed += 1
            continue
        # Dual-room inventory: blank room flags clear once room is filled.
        if (payload.get("flagType") or "") == "missing_room":
            if (block.room_text or "").strip():
                db.delete(row)
                removed += 1
            continue
        if not surgeon_id:
            db.delete(row)
            removed += 1
            continue
        link = (
            db.query(ORBlockAssignment)
            .filter(
                ORBlockAssignment.block_instance_id == block_id,
                ORBlockAssignment.surgeon_id == surgeon_id,
            )
            .first()
        )
        if not link and block.assigned_surgeon_id != surgeon_id:
            db.delete(row)
            removed += 1
            continue
        warnings = _without_on_call_warnings(block_assignment_warnings(db, block, surgeon_id))
        stored = payload.get("warnings") if isinstance(payload.get("warnings"), list) else []
        if not warnings or (
            _is_on_call_warning(row.body or "") and not _without_on_call_warnings([str(w) for w in stored])
        ):
            db.delete(row)
            removed += 1
    removed += _reconcile_stale_desk_or_schedule_flag_events(db)
    if removed:
        db.commit()
    return removed


def reconcile_ingest_correction_notifications(
    db: Session,
    admin_user_id: int | None = None,
) -> int:
    """Drop Desk ingest-correction cards once Shannon (or a later fax) fixed the field."""
    from .models import SurgicalCase

    q = db.query(AdminNotification).filter(AdminNotification.kind == "ingest_correction")
    if admin_user_id is not None:
        q = q.filter(AdminNotification.admin_user_id == admin_user_id)
    removed = 0
    for row in q.all():
        try:
            payload = json.loads(row.payload or "{}") if row.payload else {}
        except (TypeError, ValueError):
            payload = {}
        reason = payload.get("reason") or ""
        # Advent room codes and OCR-mangled names are not admin work.
        if reason in {"incomplete_room", "truncated_name"}:
            db.delete(row)
            removed += 1
            continue
        case_id = payload.get("caseId")
        if not case_id:
            continue
        case = db.get(SurgicalCase, int(case_id))
        if case is None or (case.status or "") == "cancelled":
            db.delete(row)
            removed += 1
            continue
    if removed:
        db.commit()
    return removed


def _reconcile_stale_desk_or_schedule_flag_events(db: Session) -> int:
    """Drop leftover Desk OR flag rows that are on-call-only or no longer real."""
    from .models import ORBlockAssignment, ORBlockInstance, ScheduleChangeEvent
    from .or_block_service import ACTIVE_BLOCK_STATUSES, block_assignment_warnings

    rows = (
        db.query(ScheduleChangeEvent)
        .filter(ScheduleChangeEvent.event_type == "desk_or_schedule_flag")
        .all()
    )
    removed = 0
    for row in rows:
        try:
            payload = json.loads(row.payload or "{}") if row.payload else {}
        except (TypeError, ValueError):
            payload = {}
        if _is_past_flag_date(_coerce_flag_date(payload, row.date)):
            db.delete(row)
            removed += 1
            continue
        try:
            block_id = int(payload["blockId"]) if payload.get("blockId") is not None else None
        except (TypeError, ValueError):
            block_id = None
        surgeon_id = row.surgeon_id
        stored = payload.get("warnings") if isinstance(payload.get("warnings"), list) else []
        if _is_on_call_warning(row.body or "") and not _without_on_call_warnings([str(w) for w in stored]):
            db.delete(row)
            removed += 1
            continue
        if not block_id or not surgeon_id:
            continue
        block = db.get(ORBlockInstance, block_id)
        if block is None or (block.status or "") not in ACTIVE_BLOCK_STATUSES:
            db.delete(row)
            removed += 1
            continue
        link = (
            db.query(ORBlockAssignment)
            .filter(
                ORBlockAssignment.block_instance_id == block_id,
                ORBlockAssignment.surgeon_id == surgeon_id,
            )
            .first()
        )
        if not link and block.assigned_surgeon_id != surgeon_id:
            db.delete(row)
            removed += 1
            continue
        warnings = _without_on_call_warnings(block_assignment_warnings(db, block, surgeon_id))
        if not warnings:
            db.delete(row)
            removed += 1
    return removed


def recent_admin_notifications(db: Session, admin_user_id: int, limit: int = 20) -> list[AdminNotification]:
    """FIFO: oldest entered first (top-left → right → down). Unread before read.

    Day-off / schedule-flag cards only appear while the underlying issue is still open.
    Duplicate notify spam is collapsed (one card per dayOffId / block+surgeon).
    """
    reconcile_stale_dayoff_notifications(db, admin_user_id)
    reconcile_stale_schedule_flag_notifications(db, admin_user_id)
    reconcile_ingest_correction_notifications(db, admin_user_id)
    rows = (
        db.query(AdminNotification)
        .filter(AdminNotification.admin_user_id == admin_user_id)
        .order_by(
            case((AdminNotification.read_at.is_(None), 0), else_=1),
            AdminNotification.created_at.asc().nullsfirst(),
            AdminNotification.id.asc(),
        )
        .limit(max(limit * 5, 40))
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
    seen_flags: set[tuple[int, int]] = set()
    seen_corrections: set[str] = set()
    visible: list[AdminNotification] = []
    for row in rows:
        if row.kind == "day_off_request":
            dayoff_id = _dayoff_id_from_notification(row)
            if dayoff_id is not None:
                if dayoff_id in seen_dayoff:
                    continue
                seen_dayoff.add(dayoff_id)
        elif row.kind == "schedule_flag":
            block_id, surgeon_id = _schedule_flag_keys(row)
            if block_id is not None and surgeon_id is not None:
                key = (block_id, surgeon_id)
                if key in seen_flags:
                    continue
                seen_flags.add(key)
        elif row.kind == "ingest_correction":
            try:
                fp = str((json.loads(row.payload or "{}") or {}).get("fingerprint") or row.id)
            except (TypeError, ValueError):
                fp = str(row.id)
            if fp in seen_corrections:
                continue
            seen_corrections.add(fp)
        visible.append(row)
        if len(visible) >= limit:
            break
    return visible


def unread_admin_notification_count(db: Session, admin_user_id: int) -> int:
    reconcile_stale_dayoff_notifications(db, admin_user_id)
    reconcile_stale_schedule_flag_notifications(db, admin_user_id)
    reconcile_ingest_correction_notifications(db, admin_user_id)
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
    seen_flags: set[tuple[int, int]] = set()
    seen_corrections: set[str] = set()
    count = 0
    for row in rows:
        if row.kind == "day_off_request":
            dayoff_id = _dayoff_id_from_notification(row)
            if dayoff_id is not None:
                if dayoff_id in seen_dayoff:
                    continue
                seen_dayoff.add(dayoff_id)
        elif row.kind == "schedule_flag":
            block_id, surgeon_id = _schedule_flag_keys(row)
            if block_id is not None and surgeon_id is not None:
                key = (block_id, surgeon_id)
                if key in seen_flags:
                    continue
                seen_flags.add(key)
        elif row.kind == "ingest_correction":
            try:
                fp = str((json.loads(row.payload or "{}") or {}).get("fingerprint") or row.id)
            except (TypeError, ValueError):
                fp = str(row.id)
            if fp in seen_corrections:
                continue
            seen_corrections.add(fp)
        count += 1
    return count


def rules_engine_settings(db: Session) -> tuple[dict, list]:
    from .rules_engine.engine import get_rule_config
    from .rules_engine.registry import ALL_RULES as _ALL_RULES

    return get_rule_config(db), list(_ALL_RULES) if _ALL_RULES else []
