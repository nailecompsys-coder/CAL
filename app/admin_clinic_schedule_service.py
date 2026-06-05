"""Services for admin clinic schedule pages and actions."""

from datetime import date, timedelta

from sqlalchemy.orm import Session

from .conflicts import check_conflicts
from .models import ClinicSchedule, Location, Surgeon, SurgicalCase
from .push import send_push_to_surgeon


def week_days_for_offset(week_offset: int) -> tuple[date, list[date]]:
    today = date.today()
    week_start = today - timedelta(days=today.weekday()) + timedelta(weeks=week_offset)
    return today, [week_start + timedelta(days=i) for i in range(7)]


def schedule_rows_for_slot(query, session: str):
    session = (session or "full").lower()
    if session == "full":
        return query.all()
    return query.filter(
        ClinicSchedule.session.in_([session, "full"])
    ).all()


def surgical_case_json(cases: list[SurgicalCase]) -> list[dict]:
    return [
        {
            "id": case.id,
            "surgeon_id": case.surgeon_id,
            "date": case.date.isoformat(),
            "start": case.start_time.strftime("%H:%M") if case.start_time else "08:00",
            "end": case.end_time.strftime("%H:%M") if case.end_time else None,
            "patient": case.patient_name or "",
            "patient_dob": case.patient_dob or "",
            "patient_phone": case.patient_phone or "",
            "procedure": case.procedure or "",
            "procedure_short": (case.procedure or "")[:80],
            "location_id": case.location_id or "",
            "room": (case.location.name if case.location else None) or case.room_text or "",
            "room_text": case.room_text or "",
            "status": case.status or "scheduled",
            "notes": case.notes or "",
        }
        for case in cases
    ]


def page_data(db: Session, week_offset: int) -> dict:
    today, week_days = week_days_for_offset(week_offset)
    all_locations = db.query(Location).filter(
        Location.is_active == True,
    ).order_by(Location.location_type, Location.name).all()
    schedules = db.query(ClinicSchedule).filter(
        ClinicSchedule.date >= week_days[0],
        ClinicSchedule.date <= week_days[6],
    ).all()
    sched_map = {}
    for schedule in schedules:
        sched_map.setdefault(schedule.surgeon_id, {}).setdefault(schedule.date, []).append(schedule)

    surgical_cases = (
        db.query(SurgicalCase)
        .filter(
            SurgicalCase.date >= week_days[0],
            SurgicalCase.date <= week_days[6],
            SurgicalCase.status != "cancelled",
        )
        .order_by(SurgicalCase.date, SurgicalCase.start_time)
        .all()
    )
    surgical_map = {}
    for case in surgical_cases:
        surgical_map.setdefault(case.surgeon_id, {}).setdefault(case.date, []).append(case)

    surgical_cases_json = {}
    for surgeon_id, day_cases in surgical_map.items():
        for day, cases in day_cases.items():
            surgical_cases_json[f"{surgeon_id}_{day.isoformat()}"] = surgical_case_json(cases)

    return {
        "today": today,
        "week_days": week_days,
        "all_locations": all_locations,
        "clinic_locations": [loc for loc in all_locations if loc.location_type == "clinic"],
        "hospital_locations": [loc for loc in all_locations if loc.location_type == "hospital"],
        "sched_map": sched_map,
        "surgical_map": surgical_map,
        "surgical_cases_json": surgical_cases_json,
    }


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
