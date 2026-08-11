"""Persistent audit trail for on-call assign / clear / cover changes."""

from __future__ import annotations

from datetime import date

from sqlalchemy.orm import Session, joinedload

from .models import AdminUser, CallGroup, CallScheduleAuditLog, Surgeon


def actor_label_for_admin(admin: AdminUser | None) -> str:
    if not admin:
        return "Portal"
    return admin.full_name or admin.username or "Portal"


def actor_label_for_surgeon(surgeon: Surgeon | None) -> str:
    if not surgeon:
        return "Surgeon app"
    name = surgeon.full_name or ""
    if surgeon.suffix:
        name = f"{name} {surgeon.suffix}".strip()
    return name or surgeon.initials or "Surgeon app"


def log_call_schedule_change(
    db: Session,
    *,
    action: str,
    event_date: date,
    source: str = "portal",
    call_group_id: int | None = None,
    call_group_name: str | None = None,
    rotation_id: int | None = None,
    coverage_id: int | None = None,
    from_surgeon_id: int | None = None,
    to_surgeon_id: int | None = None,
    actor_admin_id: int | None = None,
    actor_surgeon_id: int | None = None,
    actor_label: str | None = None,
    notes: str | None = None,
    commit: bool = False,
) -> CallScheduleAuditLog:
    if not call_group_name and call_group_id:
        group = db.get(CallGroup, call_group_id)
        call_group_name = group.name if group else None

    label = (actor_label or "").strip()
    if not label:
        if actor_admin_id:
            label = actor_label_for_admin(db.get(AdminUser, actor_admin_id))
        elif actor_surgeon_id:
            label = actor_label_for_surgeon(db.get(Surgeon, actor_surgeon_id))
        else:
            label = "Portal" if source == "portal" else "Surgeon app"

    row = CallScheduleAuditLog(
        action=action,
        source=source if source in ("portal", "native") else "portal",
        event_date=event_date,
        call_group_id=call_group_id,
        call_group_name=(call_group_name or "")[:128] or None,
        rotation_id=rotation_id,
        coverage_id=coverage_id,
        from_surgeon_id=from_surgeon_id,
        to_surgeon_id=to_surgeon_id,
        actor_admin_id=actor_admin_id,
        actor_surgeon_id=actor_surgeon_id,
        actor_label=label[:255],
        notes=(notes or "").strip()[:500] or None,
    )
    db.add(row)
    if commit:
        db.commit()
        db.refresh(row)
    else:
        db.flush()
    return row


def recent_call_schedule_audit_logs(
    db: Session,
    *,
    limit: int = 100,
    call_group_id: int | None = None,
) -> list[CallScheduleAuditLog]:
    q = (
        db.query(CallScheduleAuditLog)
        .options(
            joinedload(CallScheduleAuditLog.from_surgeon),
            joinedload(CallScheduleAuditLog.to_surgeon),
            joinedload(CallScheduleAuditLog.actor_admin),
            joinedload(CallScheduleAuditLog.actor_surgeon),
            joinedload(CallScheduleAuditLog.call_group),
        )
        .order_by(CallScheduleAuditLog.created_at.desc(), CallScheduleAuditLog.id.desc())
    )
    if call_group_id is not None:
        q = q.filter(CallScheduleAuditLog.call_group_id == call_group_id)
    return q.limit(max(1, min(limit, 500))).all()


def surgeon_label(surgeon: Surgeon | None) -> str:
    if not surgeon:
        return "— (clear)"
    return surgeon.full_name or surgeon.initials or f"#{surgeon.id}"
