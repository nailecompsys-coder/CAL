"""Optional call backup; the primary call assignment is never changed here."""

from fastapi import HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from .call_schedule_audit_service import actor_label_for_admin, log_call_schedule_change
from .conflicts import check_conflicts_structured
from .models import AdminUser, CallBackup, CallRotation, DayOff, Surgeon
from .practice_time import practice_today
from .surgeon_visibility import surgeon_is_visible


def validate_backup_choice(db: Session, call_date, primary_id: int | None, backup_id: int | None,
                           note: str, *, active_coverage: bool = False) -> str:
    if call_date < practice_today():
        raise HTTPException(400, "Backup can only be set for today or later")
    if active_coverage:
        raise HTTPException(400, "Clear the active coverage swap before setting a backup")
    clean_note = note.strip()
    if len(clean_note) > 500:
        raise HTTPException(400, "Note must be 500 characters or fewer")
    if backup_id is None:
        return clean_note
    primary = db.get(Surgeon, primary_id) if primary_id else None
    surgeon = db.get(Surgeon, backup_id)
    if not surgeon_is_visible(primary) or not surgeon_is_visible(surgeon) or surgeon.staff_type != primary.staff_type:
        raise HTTPException(400, "Choose an active surgeon of the same staff type")
    if surgeon.id == primary_id:
        raise HTTPException(400, "Backup must be a different surgeon")
    return clean_note


def set_backup_on_rotation(db: Session, rotation: CallRotation, surgeon_id: int | None,
                           clean_note: str, *, admin: AdminUser | None) -> None:
    old = rotation.backup
    old_id = old.surgeon_id if old else None
    old_note = old.note if old else None
    new_note = (clean_note or None) if surgeon_id else None
    if old_id == surgeon_id and old_note == new_note:
        return
    if surgeon_id is None:
        if old:
            db.delete(old)
            rotation.backup = None
    elif old:
        old.surgeon_id = surgeon_id
        old.note = new_note
    else:
        rotation.backup = CallBackup(surgeon_id=surgeon_id, note=new_note)
    if old_id is not None or surgeon_id is not None:
        log_call_schedule_change(
            db, action="backup" if surgeon_id else "backup_clear", event_date=rotation.date,
            call_group_id=rotation.call_group_id,
            call_group_name=rotation.call_group.name if rotation.call_group else None,
            rotation_id=rotation.id, from_surgeon_id=old_id, to_surgeon_id=surgeon_id,
            actor_admin_id=admin.id if admin else None, actor_label=actor_label_for_admin(admin),
            notes=new_note if surgeon_id else old_note,
        )


def save_backup(db: Session, rotation_id: int, surgeon_id: int, note: str, *, admin: AdminUser) -> list[str]:
    rotation = db.query(CallRotation).options(
        joinedload(CallRotation.surgeon), joinedload(CallRotation.call_group),
        joinedload(CallRotation.backup), joinedload(CallRotation.coverages),
    ).filter(CallRotation.id == rotation_id).first()
    if not rotation or not rotation.surgeon_id:
        raise HTTPException(404, "Assigned call date not found")
    clean_note = validate_backup_choice(db, rotation.date, rotation.surgeon_id, surgeon_id, note,
                                        active_coverage=bool(rotation.active_coverage))
    set_backup_on_rotation(db, rotation, surgeon_id, clean_note, admin=admin)
    db.commit()

    return backup_warnings(db, rotation, surgeon_id)


def backup_warnings(db: Session, rotation: CallRotation, surgeon_id: int) -> list[str]:
    surgeon = db.get(Surgeon, surgeon_id)
    conflicts = check_conflicts_structured(
        surgeon_id, rotation.date, rotation.date, db,
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
    set_backup_on_rotation(db, rotation, None, "", admin=admin)
    db.commit()
