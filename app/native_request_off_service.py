"""Business logic for native time-off requests."""
import json
from dataclasses import dataclass
from datetime import date

from fastapi import HTTPException
from sqlalchemy.orm import Session

from .conflicts import check_conflicts
from .models import DayOff, Surgeon
from .native_support import (
    normalize_day_off_segments,
    parse_hhmm,
    serialize_day_off,
    validate_day_off_segments,
)
from .push import send_native_push_to_surgeon


@dataclass(frozen=True)
class NativeRequestOffInput:
    start_date: date
    end_date: date
    reason: str = ""
    notes: str = ""
    is_full_day: bool = True
    start: str | None = None
    end: str | None = None
    segments: list[dict] | None = None


def create_native_request_off(db: Session, surgeon: Surgeon, payload: NativeRequestOffInput) -> dict:
    _validate_request_dates(payload.start_date, payload.end_date, "requested")
    segments, start_t, end_t = _request_segments(payload)

    conflict_msgs = check_conflicts(
        surgeon.id,
        payload.start_date,
        payload.end_date,
        db,
        target_entity={"type": "day_off", "start_date": payload.start_date, "end_date": payload.end_date},
    )
    overlap = _overlapping_request(db, surgeon.id, payload.start_date, payload.end_date)
    if overlap:
        conflict_msgs.append(
            f"You already have a request for {overlap.start_date.isoformat()} - {overlap.end_date.isoformat()}"
        )
    if conflict_msgs:
        return {"ok": False, "request": None, "warnings": conflict_msgs[:5]}

    row = DayOff(
        surgeon_id=surgeon.id,
        start_date=payload.start_date,
        end_date=payload.end_date,
        reason=payload.reason.strip(),
        notes=payload.notes.strip(),
        is_full_day=payload.is_full_day,
        start_time=start_t,
        end_time=end_t,
        segments=json.dumps(segments),
        status="pending",
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    send_native_push_to_surgeon(
        surgeon.id,
        "Days off request pending",
        f"{payload.start_date.strftime('%b %-d')} request sent for approval",
        db,
        {"type": "day_off", "requestId": row.id},
    )
    return {"ok": True, "request": serialize_day_off(row), "warnings": conflict_msgs[:3]}


def update_native_request_off(db: Session, surgeon: Surgeon, dayoff_id: int, payload: NativeRequestOffInput) -> dict:
    row = db.get(DayOff, dayoff_id)
    if not row or row.surgeon_id != surgeon.id:
        raise HTTPException(404, "Days off request not found")

    _validate_request_dates(payload.start_date, payload.end_date, "changed")
    segments, start_t, end_t = _request_segments(payload)

    conflict_msgs = check_conflicts(
        surgeon.id,
        payload.start_date,
        payload.end_date,
        db,
        exclude_dayoff_id=row.id,
        target_entity={"type": "day_off", "start_date": payload.start_date, "end_date": payload.end_date},
    )
    overlap = _overlapping_request(db, surgeon.id, payload.start_date, payload.end_date, exclude_id=row.id)
    if overlap:
        conflict_msgs.append(
            f"You already have a request for {overlap.start_date.isoformat()} - {overlap.end_date.isoformat()}"
        )
    if conflict_msgs:
        return {"ok": False, "request": serialize_day_off(row), "warnings": conflict_msgs[:5]}

    row.start_date = payload.start_date
    row.end_date = payload.end_date
    row.reason = payload.reason.strip()
    row.notes = payload.notes.strip()
    row.is_full_day = payload.is_full_day
    row.start_time = start_t
    row.end_time = end_t
    row.segments = json.dumps(segments)
    row.status = "pending"
    row.admin_note = None
    db.commit()
    db.refresh(row)
    send_native_push_to_surgeon(
        surgeon.id,
        "Days off request updated",
        f"{payload.start_date.strftime('%b %-d')} request updated and pending approval",
        db,
        {"type": "day_off", "requestId": row.id},
    )
    return {"ok": True, "request": serialize_day_off(row), "warnings": []}


def cancel_native_request_off(db: Session, surgeon: Surgeon, dayoff_id: int) -> dict:
    row = db.get(DayOff, dayoff_id)
    if not row or row.surgeon_id != surgeon.id:
        raise HTTPException(404, "Days off request not found")
    db.delete(row)
    db.commit()
    send_native_push_to_surgeon(
        surgeon.id,
        "Days off canceled",
        "Your schedule has been restored for the canceled days.",
        db,
        {"type": "day_off", "requestId": dayoff_id, "status": "canceled"},
    )
    return {"ok": True}


def _validate_request_dates(start_date: date, end_date: date, action: str) -> None:
    today = date.today()
    if start_date < today or end_date < today:
        raise HTTPException(400, f"Days off can only be {action} for today or later.")
    if end_date < start_date:
        raise HTTPException(400, "End date must be the same day or after the start date.")


def _request_segments(payload: NativeRequestOffInput) -> tuple[list[dict], object, object]:
    segments = normalize_day_off_segments(
        payload.start_date,
        payload.end_date,
        payload.is_full_day,
        payload.start,
        payload.end,
        payload.segments,
    )
    validate_day_off_segments(segments)
    first_partial = next((s for s in segments if not s.get("isFullDay")), None)
    start_t = parse_hhmm(first_partial.get("start")) if first_partial else None
    end_t = parse_hhmm(first_partial.get("end")) if first_partial else None
    return segments, start_t, end_t


def _overlapping_request(
    db: Session,
    surgeon_id: int,
    start_date: date,
    end_date: date,
    exclude_id: int | None = None,
) -> DayOff | None:
    query = db.query(DayOff).filter(
        DayOff.surgeon_id == surgeon_id,
        DayOff.status.in_(["pending", "approved"]),
        DayOff.start_date <= end_date,
        DayOff.end_date >= start_date,
    )
    if exclude_id is not None:
        query = query.filter(DayOff.id != exclude_id)
    return query.first()
