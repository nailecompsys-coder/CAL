from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy.orm import Session

from .conflicts import check_conflicts
from .clinic_schedule_card_guard import (
    normalize_clinic_day_cards,
    target_card_sessions,
    upsert_clinic_schedule_cards,
)
from .models import ClinicSchedule, Location, Surgeon
from .practice_time import practice_today
from .or_block_service import log_schedule_change


def schedule_rows_for_slot(query, session: str):
    session = (session or "full").lower()
    if session == "full":
        return query.all()
    return query.filter(
        ClinicSchedule.session.in_([session, "full"])
    ).all()


def assign_clinic(
    db: Session,
    schedule_date: date,
    surgeon_id: int,
    location_choice: str,
    session: str,
    notes: str,
    schedule_id: int | None = None,
) -> list[str]:
    if location_choice == "__off__":
        return ["Use Days Off to mark approved OFF time. Blank schedule slots display as NA."]

    if schedule_id:
        selected_schedule = db.get(ClinicSchedule, schedule_id)
        if not selected_schedule:
            return ["Selected clinic/OR assignment was not found. Refresh the page and try again."]
        if selected_schedule.surgeon_id != surgeon_id:
            return ["Selected clinic/OR assignment no longer matches this surgeon. Refresh the page and try again."]
        if selected_schedule.date != schedule_date:
            return ["Selected clinic/OR assignment no longer matches this date. Refresh the page and try again."]
        db.delete(selected_schedule)
        db.flush()

    assignment_type = "assigned"
    location_id = int(location_choice)
    upsert_clinic_schedule_cards(
        db,
        surgeon_id=surgeon_id,
        day=schedule_date,
        location_id=location_id,
        session=session,
        assignment_type=assignment_type,
        notes=notes,
        replace_day=(session or "").lower() == "full",
    )
    schedule = (
        db.query(ClinicSchedule)
        .filter(
            ClinicSchedule.surgeon_id == surgeon_id,
            ClinicSchedule.date == schedule_date,
            ClinicSchedule.session == target_card_sessions(session)[0],
        )
        .first()
    )
    db.commit()

    surgeon = db.get(Surgeon, surgeon_id)
    loc = db.get(Location, location_id) if location_id else None
    if not surgeon:
        return []
    if not loc:
        return []
    log_schedule_change(
        db,
        event_type="clinic_schedule_updated",
        surgeon_id=surgeon_id,
        event_date=schedule_date,
        title="Clinic/OR schedule updated",
        body=f"{surgeon.initials}: {loc.abbreviation or loc.name} {session.upper()}",
    )
    db.commit()
    # No surgeon push/SMS/email for clinic assigns until notification prefs exist.
    raw = check_conflicts(
        surgeon_id, schedule_date, schedule_date, db,
        exclude_clinic_schedule_id=schedule.id if schedule else None,
        target_entity={"type": "clinic_schedule", "date": schedule_date, "session": session},
    )
    return [f"{surgeon.full_name}: " + conflict for conflict in raw]


def clear_clinic(db: Session, schedule_id: int) -> None:
    schedule = db.get(ClinicSchedule, schedule_id)
    if schedule:
        db.delete(schedule)
        db.commit()


def copy_clinic_week(db: Session, source_offset: int, surgeon_id: str) -> dict:
    today = practice_today()
    src_start = today - timedelta(days=today.weekday()) + timedelta(weeks=source_offset)
    src_end = src_start + timedelta(days=6)
    dst_start = src_start + timedelta(weeks=1)
    dst_end = dst_start + timedelta(days=6)

    src_query = db.query(ClinicSchedule).filter(
        ClinicSchedule.date >= src_start,
        ClinicSchedule.date <= src_end,
    )
    dst_query = db.query(ClinicSchedule).filter(
        ClinicSchedule.date >= dst_start,
        ClinicSchedule.date <= dst_end,
    )

    if surgeon_id != "all":
        try:
            surgeon_filter = int(surgeon_id)
        except ValueError:
            return {"ok": False}
        src_query = src_query.filter(ClinicSchedule.surgeon_id == surgeon_filter)
        dst_query = dst_query.filter(ClinicSchedule.surgeon_id == surgeon_filter)

    src_schedules = src_query.all()
    dst_schedules = dst_query.all()

    replaced = len(dst_schedules)
    for existing in dst_schedules:
        db.delete(existing)

    created = 0
    for schedule in src_schedules:
        offset = (schedule.date - src_start).days
        new_date = dst_start + timedelta(days=offset)
        upsert_clinic_schedule_cards(
            db,
            surgeon_id=schedule.surgeon_id,
            day=new_date,
            location_id=schedule.location_id,
            session=schedule.session,
            assignment_type=schedule.assignment_type or "assigned",
            notes=schedule.notes,
        )
        normalize_clinic_day_cards(db, schedule.surgeon_id, new_date)
        created += 1
    db.commit()
    return {"ok": True, "created": created, "replaced": replaced, "next_offset": source_offset + 1}
