from __future__ import annotations

from datetime import timedelta

from sqlalchemy.orm import Session

from .admin_schedule_template_common import approved_off_dates
from .models import CallRotation, CallRotationTemplate


def save_call_rotation_order(db: Session, call_group_id: int, surgeon_ids: list[str]) -> str:
    if not surgeon_ids:
        return "no_surgeons"

    db.query(CallRotationTemplate).filter(
        CallRotationTemplate.call_group_id == call_group_id
    ).delete()

    for pos, sid in enumerate(surgeon_ids, start=1):
        db.add(CallRotationTemplate(
            call_group_id=call_group_id,
            surgeon_id=int(sid),
            position=pos,
        ))
    db.commit()
    return "rotation_saved"


def call_rotation_result_url(result: dict) -> str:
    if result["no_rotation"]:
        return "/admin/schedule-templates?tab=call&msg=no_rotation"
    return (
        "/admin/schedule-templates?tab=call&msg=call_filled"
        f"&created={result['created']}"
        f"&skipped={result['skipped']}"
    )


def call_rotation_template(db: Session, call_group_id: int) -> list[CallRotationTemplate]:
    return (
        db.query(CallRotationTemplate)
        .filter(CallRotationTemplate.call_group_id == call_group_id)
        .order_by(CallRotationTemplate.position)
        .all()
    )


def auto_fill_call_rotation(
    db: Session,
    call_group_id: int,
    start_date,
    end_date,
    start_position: int,
    days_per_surgeon: int,
    skip_existing: bool,
    rotation_type: str,
) -> dict:
    rotation = call_rotation_template(db, call_group_id)
    if not rotation:
        return {"created": 0, "skipped": 0, "no_rotation": True}

    surgeon_ids = [r.surgeon_id for r in rotation]
    off_dates = approved_off_dates(db, surgeon_ids, start_date, end_date)

    n = len(rotation)
    rot_idx = (start_position - 1) % n
    day_count = 0
    created = 0
    skipped = 0

    cur_date = start_date
    while cur_date <= end_date:
        attempts = 0
        while attempts < n:
            surgeon = rotation[rot_idx]
            if (surgeon.surgeon_id, cur_date) not in off_dates:
                break
            rot_idx = (rot_idx + 1) % n
            day_count = 0
            attempts += 1
        else:
            cur_date += timedelta(days=1)
            continue

        if skip_existing:
            exists = db.query(CallRotation).filter(
                CallRotation.date == cur_date,
                CallRotation.call_group_id == call_group_id,
                CallRotation.rotation_type == rotation_type,
            ).first()
            if exists:
                skipped += 1
                cur_date += timedelta(days=1)
                day_count += 1
                if day_count >= days_per_surgeon:
                    rot_idx = (rot_idx + 1) % n
                    day_count = 0
                continue

        db.add(CallRotation(
            surgeon_id=surgeon.surgeon_id,
            date=cur_date,
            rotation_type=rotation_type,
            call_group_id=call_group_id,
        ))
        created += 1

        day_count += 1
        if day_count >= days_per_surgeon:
            rot_idx = (rot_idx + 1) % n
            day_count = 0

        cur_date += timedelta(days=1)

    db.commit()
    return {"created": created, "skipped": skipped, "no_rotation": False}
