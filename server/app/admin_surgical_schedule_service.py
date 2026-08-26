"""Services for admin surgical schedule routes."""

import urllib.parse
from datetime import date, datetime, time, timedelta

from sqlalchemy.orm import Session

from .models import SurgicalCase
from .practice_time import practice_today
from .push import send_push_to_surgeon
from .scheduling_guardrails_service import surgical_case_warning_messages


def week_offset_for_date(target_date: date) -> int:
    today = practice_today()
    week_start = today - timedelta(days=today.weekday())
    return (target_date - week_start).days // 7


def surgery_fields(
    surgeon_id: int,
    case_date: str,
    start_time: str,
    patient_name: str,
    procedure: str,
    end_time: str,
    patient_dob: str,
    patient_phone: str,
    location_id: str,
    room_text: str,
    status: str,
    notes: str,
) -> dict:
    parsed_date = date.fromisoformat(case_date.strip())
    start = datetime.strptime(start_time, "%H:%M").time() if start_time else time(8, 0)
    end = datetime.strptime(end_time, "%H:%M").time() if end_time else None
    loc_id = int(location_id) if location_id and location_id.strip() else None
    return {
        "surgeon_id": surgeon_id,
        "date": parsed_date,
        "start_time": start,
        "end_time": end,
        "patient_name": patient_name.strip(),
        "patient_dob": patient_dob.strip() or None,
        "patient_phone": patient_phone.strip() or None,
        "procedure": procedure.strip(),
        "location_id": loc_id,
        "room_text": room_text.strip() or None,
        "status": status,
        "notes": notes.strip() or None,
    }


def conflict_warning_query(db: Session, surgical_case: SurgicalCase, exclude_case_id: int | None = None) -> str:
    conflicts = surgical_case_warning_messages(
        db,
        surgical_case.surgeon_id,
        surgical_case.date,
        surgical_case.start_time,
        surgical_case.end_time,
        surgical_case.location_id,
        exclude_case_id,
    )
    if not conflicts:
        return ""
    return "&warn=" + urllib.parse.quote(" · ".join(conflicts[:8]))


def add_surgical_case(
    db: Session, fields: dict, *, notify: bool = True
) -> tuple[SurgicalCase, str]:
    surgical_case = SurgicalCase(**fields)
    db.add(surgical_case)
    db.commit()
    if notify:
        send_push_to_surgeon(
            surgical_case.surgeon_id,
            "Schedule updated",
            f"Surgery added {surgical_case.date.strftime('%b %-d')} {surgical_case.start_time.strftime('%-I:%M %p')}",
            db,
        )
    return surgical_case, conflict_warning_query(db, surgical_case, exclude_case_id=surgical_case.id)


def update_surgical_case(db: Session, surgical_case: SurgicalCase, fields: dict) -> str:
    for key, value in fields.items():
        setattr(surgical_case, key, value)
    db.commit()
    send_push_to_surgeon(
        surgical_case.surgeon_id,
        "Schedule updated",
        f"Surgery updated {surgical_case.date.strftime('%b %-d')} {surgical_case.start_time.strftime('%-I:%M %p')}",
        db,
    )
    return conflict_warning_query(db, surgical_case, exclude_case_id=surgical_case.id)


def delete_surgical_case(db: Session, surgical_case: SurgicalCase) -> date:
    parsed_date = surgical_case.date
    db.delete(surgical_case)
    db.commit()
    return parsed_date
