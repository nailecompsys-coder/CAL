"""Services for admin surgical schedule routes."""

import urllib.parse
from datetime import date, datetime, time, timedelta

from sqlalchemy.orm import Session

from .models import Location, ORBlockAssignment, ORBlockInstance, SurgicalCase
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


def _is_cbo_location(loc: Location | None) -> bool:
    if not loc:
        return False
    text = f"{loc.abbreviation or ''} {loc.name or ''}".upper()
    compact = "".join(ch for ch in text if ch.isalnum())
    return "CBO" in compact or "SURGERYONE" in compact or "SURGICALONE" in compact


def _matching_assigned_block(db: Session, fields: dict, *, exclude_case_id: int | None = None) -> ORBlockInstance | None:
    surgeon_id = int(fields.get("surgeon_id") or 0)
    case_date = fields.get("date")
    start_time = fields.get("start_time")
    location_id = fields.get("location_id")
    block_id = fields.get("or_block_instance_id")
    if not surgeon_id or not case_date or not start_time or not location_id:
        return None

    q = (
        db.query(ORBlockInstance)
        .join(ORBlockAssignment, ORBlockAssignment.block_instance_id == ORBlockInstance.id)
        .filter(
            ORBlockAssignment.surgeon_id == surgeon_id,
            ORBlockInstance.date == case_date,
            ORBlockInstance.location_id == int(location_id),
            ORBlockInstance.status == "assigned",
            ORBlockInstance.start_time <= start_time,
            ORBlockInstance.end_time > start_time,
        )
        .order_by(ORBlockInstance.start_time, ORBlockInstance.id)
    )
    if block_id:
        q = q.filter(ORBlockInstance.id == int(block_id))
    block = q.first()
    if not block:
        return None

    overlap = (
        db.query(SurgicalCase)
        .filter(
            SurgicalCase.id != exclude_case_id if exclude_case_id else True,
            SurgicalCase.surgeon_id == surgeon_id,
            SurgicalCase.date == case_date,
            SurgicalCase.status != "cancelled",
            SurgicalCase.start_time == start_time,
        )
        .first()
    )
    if overlap:
        raise ValueError("Schedule collision: this surgeon already has a case at that time.")
    return block


def enforce_surgical_case_write_guardrails(
    db: Session,
    fields: dict,
    *,
    exclude_case_id: int | None = None,
) -> dict:
    """Hard write gate for portal, mobile scheduler, API ingest, and OCR.

    Cases must fit a static assigned Block OR row. CBO / Surgery One is Aprima
    only and may not be written as a manual/fax surgical case.
    """
    loc = db.get(Location, int(fields["location_id"])) if fields.get("location_id") else None
    if _is_cbo_location(loc):
        raise ValueError("CBO / Surgery One cases come from Aprima only.")

    block = _matching_assigned_block(db, fields, exclude_case_id=exclude_case_id)
    if not block:
        raise ValueError("Case must fit an assigned static Block OR slot for that surgeon, location, date, and time.")

    out = dict(fields)
    out["or_block_instance_id"] = block.id
    out["location_id"] = block.location_id
    if block.room_text and not (out.get("room_text") or "").strip():
        out["room_text"] = block.room_text
    return out


def add_surgical_case(
    db: Session, fields: dict, *, notify: bool = True
) -> tuple[SurgicalCase, str]:
    fields = enforce_surgical_case_write_guardrails(db, fields)
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
    fields = enforce_surgical_case_write_guardrails(db, fields, exclude_case_id=surgical_case.id)
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
