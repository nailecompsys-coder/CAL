"""Services for admin surgical schedule routes."""

import urllib.parse
import uuid
from datetime import date, datetime, time, timedelta

from sqlalchemy.orm import Session

from .models import Location, ORBlockAssignment, ORBlockInstance, ScheduleCard, ScheduleCardActivity
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


def conflict_warning_query(db: Session, line: ScheduleCardActivity) -> str:
    conflicts = surgical_case_warning_messages(
        db,
        line.surgeon_id,
        line.activity_date,
        line.start_time,
        line.end_time,
        line.location_id,
        exclude_activity_id=line.id,
        or_block_instance_id=line.or_block_instance_id,
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
        db.query(ScheduleCardActivity)
        .filter(
            ScheduleCardActivity.id != exclude_case_id if exclude_case_id else True,
            ScheduleCardActivity.surgeon_id == surgeon_id,
            ScheduleCardActivity.activity_date == case_date,
            ScheduleCardActivity.activity_type == "surgical",
            ScheduleCardActivity.is_active == True,  # noqa: E712
            ScheduleCardActivity.start_time == start_time,
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


def _card_for_surgery(db: Session, fields: dict) -> ScheduleCard:
    from .schedule_activity_normalization import resolve_schedule_card

    start = fields.get("start_time")
    session = "pm" if start and start >= time(12, 0) else "am"
    card = resolve_schedule_card(
        db,
        surgeon_id=fields.get("surgeon_id"),
        day=fields.get("date"),
        location_id=fields.get("location_id"),
        start_time=start,
        preferred_session=session,
    )
    if card is None:
        raise ValueError("This surgeon has no morning or afternoon card for that day.")
    return card


def _write_surgery_line(
    db: Session,
    card: ScheduleCard,
    fields: dict,
    *,
    source_system: str,
    source_record_key: str,
) -> ScheduleCardActivity:
    from .schedule_activity_normalization import _upsert_activity

    return _upsert_activity(
        db,
        source_system=source_system,
        source_record_key=source_record_key,
        card=card,
        activity_type="surgical",
        start_time=fields.get("start_time"),
        end_time=fields.get("end_time"),
        patient_name=fields.get("patient_name") or "Patient",
        procedure=fields.get("procedure") or "",
        room_text=fields.get("room_text"),
        location_id=fields.get("location_id"),
        is_active=(fields.get("status") or "scheduled") != "cancelled",
        or_block_instance_id=fields.get("or_block_instance_id"),
    )


def add_surgical_case(
    db: Session, fields: dict, *, notify: bool = True
) -> tuple[ScheduleCardActivity, str]:
    fields = enforce_surgical_case_write_guardrails(db, fields)
    card = _card_for_surgery(db, fields)
    line = _write_surgery_line(
        db,
        card,
        fields,
        source_system="portal",
        source_record_key=uuid.uuid4().hex,
    )
    db.commit()
    if notify and line.start_time:
        send_push_to_surgeon(
            line.surgeon_id,
            "Schedule updated",
            f"Surgery added {line.activity_date.strftime('%b %-d')} {line.start_time.strftime('%-I:%M %p')}",
            db,
        )
    return line, conflict_warning_query(db, line)


def update_surgical_case(db: Session, line: ScheduleCardActivity, fields: dict) -> str:
    fields = enforce_surgical_case_write_guardrails(db, fields, exclude_case_id=line.id)
    card = _card_for_surgery(db, fields)
    line = _write_surgery_line(
        db,
        card,
        fields,
        source_system=line.source_system,
        source_record_key=line.source_record_key,
    )
    db.commit()
    if line.start_time:
        send_push_to_surgeon(
            line.surgeon_id,
            "Schedule updated",
            f"Surgery updated {line.activity_date.strftime('%b %-d')} {line.start_time.strftime('%-I:%M %p')}",
            db,
        )
    return conflict_warning_query(db, line)


def delete_surgical_case(db: Session, line: ScheduleCardActivity) -> date:
    parsed_date = line.activity_date
    line.is_active = False
    db.commit()
    return parsed_date
