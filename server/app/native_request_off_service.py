"""Business logic for native time-off requests."""
import json
from datetime import date

from fastapi import HTTPException
from sqlalchemy.orm import Session

from .models import DayOff, Surgeon
from .native_request_off_helpers import (
    NativeRequestOffInput,
    overlapping_request,
    request_segments,
    validate_request_dates,
)
from .native_support import serialize_day_off
from .push import notify_admins, send_native_push_to_surgeon
from .scheduling_guardrails_service import dayoff_surgeon_warning, store_dayoff_findings


def create_native_request_off(db: Session, surgeon: Surgeon, payload: NativeRequestOffInput) -> dict:
    _validate_request_dates(payload.start_date, payload.end_date, "requested")
    segments, start_t, end_t = _request_segments(payload)

    conflict_msgs = []
    overlap = _overlapping_request(db, surgeon.id, payload.start_date, payload.end_date)
    if overlap:
        conflict_msgs.append(
            f"You already have a request for {overlap.start_date.isoformat()} - {overlap.end_date.isoformat()}"
        )

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
    findings = store_dayoff_findings(db, row)
    if findings:
        conflict_msgs.append(dayoff_surgeon_warning(findings))
    notify_admins(
        "CAL request pending",
        f"{surgeon.full_name} requested {payload.start_date.strftime('%b %-d')} to {payload.end_date.strftime('%b %-d')}.",
        db,
        kind="day_off_request",
        payload={"dayOffId": row.id, "surgeonId": surgeon.id},
        require_dayoff_opt_in=True,
    )
    send_native_push_to_surgeon(
        surgeon.id,
        "Days off request pending",
        f"{payload.start_date.strftime('%b %-d')} request sent for approval",
        db,
        {"type": "day_off", "requestId": row.id},
    )
    return {"ok": True, "request": serialize_day_off(row), "warnings": [msg for msg in conflict_msgs if msg][:3]}


def update_native_request_off(db: Session, surgeon: Surgeon, dayoff_id: int, payload: NativeRequestOffInput) -> dict:
    row = db.get(DayOff, dayoff_id)
    if not row or row.surgeon_id != surgeon.id:
        raise HTTPException(404, "Days off request not found")

    _validate_request_dates(payload.start_date, payload.end_date, "changed")
    segments, start_t, end_t = _request_segments(payload)

    conflict_msgs = []
    overlap = _overlapping_request(db, surgeon.id, payload.start_date, payload.end_date, exclude_id=row.id)
    if overlap:
        conflict_msgs.append(
            f"You already have a request for {overlap.start_date.isoformat()} - {overlap.end_date.isoformat()}"
        )

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
    findings = store_dayoff_findings(db, row)
    conflict_msgs.extend([dayoff_surgeon_warning(findings)] if findings else [])
    notify_admins(
        "CAL request updated",
        f"{surgeon.full_name} updated request {payload.start_date.strftime('%b %-d')} to {payload.end_date.strftime('%b %-d')}.",
        db,
        kind="day_off_request",
        payload={"dayOffId": row.id, "surgeonId": surgeon.id},
        require_dayoff_opt_in=True,
    )
    send_native_push_to_surgeon(
        surgeon.id,
        "Days off request updated",
        f"{payload.start_date.strftime('%b %-d')} request updated and pending approval",
        db,
        {"type": "day_off", "requestId": row.id},
    )
    return {"ok": True, "request": serialize_day_off(row), "warnings": [msg for msg in conflict_msgs if msg][:3]}


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
    validate_request_dates(start_date, end_date, action)


def _request_segments(payload: NativeRequestOffInput) -> tuple[list[dict], object, object]:
    return request_segments(payload)


def _overlapping_request(
    db: Session,
    surgeon_id: int,
    start_date: date,
    end_date: date,
    exclude_id: int | None = None,
) -> DayOff | None:
    return overlapping_request(db, surgeon_id, start_date, end_date, exclude_id)
