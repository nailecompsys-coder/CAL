"""Services for admin schedule templates and call rotation generation."""

from datetime import timedelta

from sqlalchemy.orm import Session

from .models import CallRotation, CallRotationTemplate, ClinicSchedule, DayOff, Surgeon, SurgeonLocationSchedule


def active_surgeon_ids(db: Session) -> list[int]:
    return [s.id for s in db.query(Surgeon.id).filter(Surgeon.is_active == True).all()]


def parse_target_surgeon_ids(db: Session, surgeon_ids: str) -> list[int]:
    if surgeon_ids == "all":
        return active_surgeon_ids(db)
    return [int(x) for x in surgeon_ids.split(",") if x.strip().isdigit()]


def approved_off_dates(db: Session, surgeon_ids: list[int], start_date, end_date) -> set[tuple[int, object]]:
    days_off_records = db.query(DayOff).filter(
        DayOff.surgeon_id.in_(surgeon_ids),
        DayOff.start_date <= end_date,
        DayOff.end_date >= start_date,
        DayOff.status == "approved",
    ).all()
    off_dates = set()
    for day_off in days_off_records:
        cur = day_off.start_date
        while cur <= day_off.end_date:
            off_dates.add((day_off.surgeon_id, cur))
            cur += timedelta(days=1)
    return off_dates


def template_cells_by_surgeon(db: Session, surgeon_ids: list[int]) -> dict:
    templates_all = db.query(SurgeonLocationSchedule).filter(
        SurgeonLocationSchedule.surgeon_id.in_(surgeon_ids),
        SurgeonLocationSchedule.assignment_type != "off",
    ).all()
    tpl_by_surgeon = {}
    for template in templates_all:
        tpl_by_surgeon.setdefault(template.surgeon_id, {}).setdefault(template.day_of_week, {})[template.session] = template
    return tpl_by_surgeon


def apply_clinic_schedule_templates(
    db: Session,
    start_date,
    end_date,
    surgeon_ids: str,
    skip_existing: bool,
    overwrite_daysoff: bool,
) -> dict:
    target_ids = parse_target_surgeon_ids(db, surgeon_ids)
    tpl_by_surgeon = template_cells_by_surgeon(db, target_ids)
    off_dates = approved_off_dates(db, target_ids, start_date, end_date)

    created = 0
    skipped_existing = 0
    skipped_off = 0
    skipped_float = 0

    cur_date = start_date
    while cur_date <= end_date:
        dow = cur_date.weekday()
        if dow > 4:
            cur_date += timedelta(days=1)
            continue

        for sid in target_ids:
            if (sid, cur_date) in off_dates and not overwrite_daysoff:
                skipped_off += 1
                continue

            day_tpls = tpl_by_surgeon.get(sid, {}).get(dow, {})
            for session, template in day_tpls.items():
                if template.assignment_type == "float":
                    skipped_float += 1
                    continue
                if template.assignment_type == "assigned" and template.location_id is None:
                    continue

                if skip_existing:
                    exists = db.query(ClinicSchedule).filter(
                        ClinicSchedule.surgeon_id == sid,
                        ClinicSchedule.date == cur_date,
                        ClinicSchedule.session == session,
                    ).first()
                    if exists:
                        skipped_existing += 1
                        continue

                db.add(ClinicSchedule(
                    surgeon_id=sid,
                    location_id=template.location_id if template.assignment_type == "assigned" else None,
                    date=cur_date,
                    session=session,
                    assignment_type=template.assignment_type,
                    notes=None,
                ))
                created += 1

        cur_date += timedelta(days=1)

    db.commit()
    return {
        "created": created,
        "skipped_existing": skipped_existing,
        "skipped_off": skipped_off,
        "skipped_float": skipped_float,
    }


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
