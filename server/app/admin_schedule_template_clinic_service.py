from __future__ import annotations

from datetime import timedelta

from sqlalchemy.orm import Session

from .admin_schedule_template_common import approved_off_dates, parse_target_surgeon_ids
from .models import CallGroup, CallRotationTemplate, ClinicSchedule, Location, Surgeon, SurgeonLocationSchedule
from .surgeon_visibility import surgeon_is_visible


def template_cells_by_surgeon(db: Session, surgeon_ids: list[int]) -> dict:
    templates_all = db.query(SurgeonLocationSchedule).filter(
        SurgeonLocationSchedule.surgeon_id.in_(surgeon_ids),
        SurgeonLocationSchedule.assignment_type != "off",
    ).all()
    tpl_by_surgeon = {}
    for template in templates_all:
        tpl_by_surgeon.setdefault(template.surgeon_id, {}).setdefault(template.day_of_week, {})[template.session] = template
    return tpl_by_surgeon


def template_grid_context(db: Session, sort_surgeons) -> dict:
    surgeons = [row for row in db.query(Surgeon).filter(Surgeon.is_active == True).all() if surgeon_is_visible(row)]
    templates_raw = db.query(SurgeonLocationSchedule).all()
    tpl_map = {}
    for template in templates_raw:
        tpl_map.setdefault(template.surgeon_id, {}).setdefault(template.day_of_week, {})[template.session] = template

    rotation_templates = db.query(CallRotationTemplate).order_by(
        CallRotationTemplate.call_group_id, CallRotationTemplate.position
    ).all()
    rotation_by_group = {}
    for rotation_template in rotation_templates:
        rotation_by_group.setdefault(rotation_template.call_group_id, []).append(rotation_template)

    return {
        "surgeons": sort_surgeons(surgeons),
        "all_locations": db.query(Location)
        .filter(Location.is_active == True)
        .order_by(Location.location_type.desc(), Location.name)
        .all(),
        "tpl_map": tpl_map,
        "call_groups": db.query(CallGroup).order_by(CallGroup.sort_order).all(),
        "rotation_by_group": rotation_by_group,
        "days": ["Mon", "Tue", "Wed", "Thu", "Fri"],
    }


def save_template_cell_value(
    db: Session,
    surgeon_id: int,
    day_of_week: int,
    session: str,
    location_id: int | None,
    assignment_type: str,
) -> dict:
    existing = db.query(SurgeonLocationSchedule).filter(
        SurgeonLocationSchedule.surgeon_id == surgeon_id,
        SurgeonLocationSchedule.day_of_week == day_of_week,
        SurgeonLocationSchedule.session == session,
    ).first()

    if assignment_type == "off" and location_id is None and existing is None:
        return {"ok": True, "action": "noop"}

    if existing:
        existing.location_id = location_id if assignment_type == "assigned" else None
        existing.assignment_type = assignment_type
    else:
        db.add(SurgeonLocationSchedule(
            surgeon_id=surgeon_id,
            day_of_week=day_of_week,
            session=session,
            location_id=location_id if assignment_type == "assigned" else None,
            assignment_type=assignment_type,
        ))
    db.commit()
    return {"ok": True, "action": "updated" if existing else "created"}


def clinic_apply_result_url(result: dict) -> str:
    return (
        "/admin/schedule-templates?msg=applied"
        f"&created={result['created']}"
        f"&skipped={result['skipped_existing']}"
        f"&off={result['skipped_off']}"
    )


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
