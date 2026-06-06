from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy.orm import Session

from .conflicts import check_conflicts
from .models import ClinicSchedule, Location, Surgeon
from .push import send_push_to_surgeon


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
) -> list[str]:
    assignment_type = "off" if location_choice == "__off__" else "assigned"
    location_id = None if assignment_type == "off" else int(location_choice)
    slot_query = db.query(ClinicSchedule).filter(
        ClinicSchedule.surgeon_id == surgeon_id,
        ClinicSchedule.date == schedule_date,
    )
    for existing in schedule_rows_for_slot(slot_query, session):
        db.delete(existing)
    db.flush()

    schedule = ClinicSchedule(
        surgeon_id=surgeon_id,
        location_id=location_id,
        date=schedule_date,
        session=session,
        assignment_type=assignment_type,
        notes=notes,
    )
    db.add(schedule)
    db.flush()
    db.commit()

    surgeon = db.get(Surgeon, surgeon_id)
    loc = db.get(Location, location_id) if location_id else None
    if not surgeon:
        return []
    if assignment_type == "off":
        send_push_to_surgeon(
            surgeon_id,
            "Schedule Updated",
            f"{schedule_date.strftime('%b %d')}: OFF",
            db,
        )
        return []
    if not loc:
        return []
    send_push_to_surgeon(
        surgeon_id,
        "Clinic Schedule Updated",
        f"{schedule_date.strftime('%b %d')}: {loc.name}",
        db,
    )
    raw = check_conflicts(
        surgeon_id, schedule_date, schedule_date, db,
        exclude_clinic_schedule_id=schedule.id,
        target_entity={"type": "clinic_schedule", "date": schedule_date, "session": session},
    )
    return [f"{surgeon.full_name}: " + conflict for conflict in raw]


def clear_clinic(db: Session, schedule_id: int) -> None:
    schedule = db.get(ClinicSchedule, schedule_id)
    if schedule:
        db.delete(schedule)
        db.commit()


def copy_clinic_week(db: Session, source_offset: int, surgeon_id: str) -> dict:
    today = date.today()
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
        db.add(ClinicSchedule(
            surgeon_id=schedule.surgeon_id,
            location_id=schedule.location_id,
            date=new_date,
            session=schedule.session,
            assignment_type=schedule.assignment_type or "assigned",
            notes=schedule.notes,
        ))
        created += 1
    db.commit()
    return {"ok": True, "created": created, "replaced": replaced, "next_offset": source_offset + 1}
