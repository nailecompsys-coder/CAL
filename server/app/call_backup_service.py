"""Optional call backup; the primary call assignment is never changed here."""

from fastapi import HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from .call_schedule_audit_service import actor_label_for_admin, log_call_schedule_change
from .conflicts import check_conflicts_structured
from .models import AdminUser, CallBackup, CallRotation, DayOff, Surgeon
from .practice_time import practice_today
from .surgeon_visibility import surgeon_is_visible


def save_backup(db: Session, rotation_id: int, surgeon_id: int, note: str, *, admin: AdminUser) -> list[str]:
    rotation = db.query(CallRotation).options(
        joinedload(CallRotation.surgeon), joinedload(CallRotation.call_group),
        joinedload(CallRotation.backup), joinedload(CallRotation.coverages),
    ).filter(CallRotation.id == rotation_id).first()
    if not rotation or not rotation.surgeon_id:
        raise HTTPException(404, "Assigned call date not found")
    if rotation.date < practice_today():
        raise HTTPException(400, "Backup can only be set for today or later")
    if rotation.active_coverage:
        raise HTTPException(400, "Clear the active coverage swap before setting a backup")
    surgeon = db.get(Surgeon, surgeon_id)
    if not surgeon_is_visible(surgeon) or surgeon.staff_type != rotation.surgeon.staff_type:
        raise HTTPException(400, "Choose an active surgeon of the same staff type")
    if surgeon.id == rotation.surgeon_id:
        raise HTTPException(400, "Backup must be a different surgeon")
    clean_note = note.strip()
    if len(clean_note) > 500:
        raise HTTPException(400, "Note must be 500 characters or fewer")

    old_id = rotation.backup.surgeon_id if rotation.backup else None
    old_note = rotation.backup.note if rotation.backup else None
    if rotation.backup:
        rotation.backup.surgeon_id = surgeon.id
        rotation.backup.note = clean_note or None
    else:
        rotation.backup = CallBackup(surgeon_id=surgeon.id, note=clean_note or None)
    if old_id != surgeon.id or old_note != (clean_note or None):
        log_call_schedule_change(
            db, action="backup", event_date=rotation.date, call_group_id=rotation.call_group_id,
            call_group_name=rotation.call_group.name if rotation.call_group else None,
            rotation_id=rotation.id, from_surgeon_id=old_id, to_surgeon_id=surgeon.id,
            actor_admin_id=admin.id, actor_label=actor_label_for_admin(admin),
            notes=clean_note or None,
        )
    db.commit()

    conflicts = check_conflicts_structured(
        surgeon.id, rotation.date, rotation.date, db,
        exclude_entity=("call_rotation", rotation.id),
        target_entity={"type": "call_coverage", "date": rotation.date},
    )
    warnings = [f"{surgeon.full_name}: {item.message}" for item in conflicts]
    if surgeon.id in approved_no_call_ids(db, rotation.date):
        warnings.insert(0, f"{surgeon.full_name}: No Call is approved for this date; review this Backup exception")
    return warnings


def approved_no_call_ids(db: Session, call_date) -> list[int]:
    rows = db.query(DayOff.surgeon_id).filter(
        DayOff.status == "approved",
        func.lower(func.trim(DayOff.reason)) == "no call",
        DayOff.start_date <= call_date,
        DayOff.end_date >= call_date,
    ).distinct().order_by(DayOff.surgeon_id).all()
    return [row.surgeon_id for row in rows]


def clear_backup(db: Session, rotation_id: int, *, admin: AdminUser) -> None:
    rotation = db.query(CallRotation).options(
        joinedload(CallRotation.call_group), joinedload(CallRotation.backup),
    ).filter(CallRotation.id == rotation_id).first()
    if not rotation or not rotation.backup:
        return
    if rotation.date < practice_today():
        raise HTTPException(400, "Past backups cannot be changed")
    old = rotation.backup
    log_call_schedule_change(
        db, action="backup_clear", event_date=rotation.date, call_group_id=rotation.call_group_id,
        call_group_name=rotation.call_group.name if rotation.call_group else None,
        rotation_id=rotation.id, from_surgeon_id=old.surgeon_id,
        actor_admin_id=admin.id, actor_label=actor_label_for_admin(admin), notes=old.note,
    )
    db.delete(old)
    db.commit()
