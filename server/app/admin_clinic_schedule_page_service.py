from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy.orm import Session

from .models import ClinicSchedule, Location, SurgicalCase


def week_days_for_offset(week_offset: int) -> tuple[date, list[date]]:
    today = date.today()
    week_start = today - timedelta(days=today.weekday()) + timedelta(weeks=week_offset)
    return today, [week_start + timedelta(days=i) for i in range(7)]


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
