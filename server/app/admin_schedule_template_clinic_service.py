from __future__ import annotations

import re
from datetime import date
from datetime import timedelta

from sqlalchemy.orm import Session

from .admin_schedule_template_common import approved_off_dates, parse_target_surgeon_ids
from .clinic_schedule_card_guard import normalize_clinic_day_cards, upsert_clinic_schedule_cards
from .models import CallGroup, CallRotationTemplate, ClinicSchedule, Location, Surgeon, SurgeonLocationSchedule
from .surgeon_visibility import surgeon_is_visible


WEEK_PATTERN_OPTIONS = [
    ("all", "Every"),
    ("1", "1"),
    ("2", "2"),
    ("3", "3"),
    ("4", "4"),
    ("5", "5"),
    ("1,3,5", "1,3,5"),
    ("2,4", "2,4"),
]

_LOCATION_ABBREVIATION_RE = re.compile(r"^[A-Z0-9 /&-]{1,12}$")


def add_master_schedule_location(
    db: Session,
    *,
    name: str,
    abbreviation: str,
    location_type: str,
) -> Location:
    """Add an active location for later assignment to existing scaffold cards."""
    clean_name = " ".join((name or "").strip().split())
    clean_abbreviation = " ".join((abbreviation or "").strip().upper().split())
    clean_type = "hospital" if (location_type or "").strip().lower() == "hospital" else "clinic"
    if not clean_name:
        raise ValueError("Location name is required.")
    if not _LOCATION_ABBREVIATION_RE.fullmatch(clean_abbreviation):
        raise ValueError("Use a 1-12 character location abbreviation.")
    if db.query(Location).filter(Location.abbreviation == clean_abbreviation).first():
        raise ValueError("That location abbreviation already exists.")
    location = Location(
        name=clean_name,
        abbreviation=clean_abbreviation,
        location_type=clean_type,
        is_active=True,
    )
    db.add(location)
    db.flush()
    return location


def normalize_week_pattern(value: str | None) -> str:
    raw = (value or "all").strip().lower()
    if raw in {"", "all", "every", "*"}:
        return "all"
    parts: list[str] = []
    for part in raw.replace("/", ",").replace(" ", "").split(","):
        if part in {"1", "2", "3", "4", "5"} and part not in parts:
            parts.append(part)
    return ",".join(parts) if parts else "all"


def month_week(day: date) -> int:
    """1-5 occurrence of this weekday inside the month."""
    return (day.day - 1) // 7 + 1


def week_pattern_matches(day: date, pattern: str | None) -> bool:
    normalized = normalize_week_pattern(pattern)
    if normalized == "all":
        return True
    return str(month_week(day)) in normalized.split(",")


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
        "week_pattern_options": WEEK_PATTERN_OPTIONS,
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
    week_pattern: str | None = "all",
    *,
    commit: bool = True,
) -> dict:
    assignment_type = (assignment_type or "assigned").lower().strip()
    week_pattern = normalize_week_pattern(week_pattern)
    existing = db.query(SurgeonLocationSchedule).filter(
        SurgeonLocationSchedule.surgeon_id == surgeon_id,
        SurgeonLocationSchedule.day_of_week == day_of_week,
        SurgeonLocationSchedule.session == session,
    ).first()

    if assignment_type in {"blank", "float"}:
        assignment_type = "na"
    if assignment_type not in {"assigned", "na", "off"}:
        raise ValueError("Unsupported master schedule state.")
    if assignment_type == "assigned" and not location_id:
        raise ValueError("A location is required for an assigned master slot.")

    if existing:
        existing.location_id = location_id if assignment_type == "assigned" else None
        existing.assignment_type = assignment_type
        existing.week_pattern = week_pattern
    else:
        db.add(SurgeonLocationSchedule(
            surgeon_id=surgeon_id,
            day_of_week=day_of_week,
            session=session,
            location_id=location_id if assignment_type == "assigned" else None,
            assignment_type=assignment_type,
            week_pattern=week_pattern,
        ))
    if commit:
        db.commit()
    else:
        db.flush()
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
                if not week_pattern_matches(cur_date, getattr(template, "week_pattern", "all")):
                    continue
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

                upsert_clinic_schedule_cards(
                    db,
                    surgeon_id=sid,
                    day=cur_date,
                    location_id=template.location_id if template.assignment_type == "assigned" else None,
                    session=session,
                    assignment_type=template.assignment_type,
                    notes=None,
                )
                normalize_clinic_day_cards(db, sid, cur_date)
                created += 1

        cur_date += timedelta(days=1)

    db.commit()
    return {
        "created": created,
        "skipped_existing": skipped_existing,
        "skipped_off": skipped_off,
        "skipped_float": skipped_float,
    }
