"""Business logic for native time-off requests."""
import json

from fastapi import HTTPException
from sqlalchemy.orm import Session

from .models import DayOff, Surgeon
from .native_request_off_helpers import (
    NativeRequestOffInput,
    request_segments,
    validate_request_dates,
)
from .native_support import serialize_day_off
from .or_block_service import log_schedule_change
from .push import notify_admins, send_native_push_to_surgeon
from .scheduling_gate_service import (
    day_off_overlap_advisory,
    find_exact_pending_day_off,
    purge_exact_pending_duplicates,
    surgeon_friendly_conflict_message,
)
from .scheduling_guardrails_service import store_dayoff_findings


def create_native_request_off(db: Session, surgeon: Surgeon, payload: NativeRequestOffInput) -> dict:
    _validate_request_dates(payload.start_date, payload.end_date, "requested")
    segments, start_t, end_t = _request_segments(payload)

    warnings: list[str] = []
    existing = find_exact_pending_day_off(
        db, surgeon.id, payload.start_date, payload.end_date
    )
    if existing:
        warnings.append("This request is already pending approval.")
        overlap_note = day_off_overlap_advisory(
            db,
            surgeon.id,
            payload.start_date,
            payload.end_date,
            exclude_id=existing.id,
        )
        if overlap_note:
            warnings.append(overlap_note)
        return {"ok": True, "request": serialize_day_off(existing), "warnings": warnings[:3]}

    overlap_note = day_off_overlap_advisory(
        db,
        surgeon.id,
        payload.start_date,
        payload.end_date,
    )
    if overlap_note:
        warnings.append(overlap_note)

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
    purge_exact_pending_duplicates(
        db,
        surgeon.id,
        payload.start_date,
        payload.end_date,
        keep_id=row.id,
    )
    db.refresh(row)
    log_schedule_change(
        db,
        event_type="day_off_requested",
        surgeon_id=surgeon.id,
        event_date=payload.start_date,
        title="Time off requested",
        body=f"{surgeon.initials}: {payload.start_date.strftime('%b %-d')} to {payload.end_date.strftime('%b %-d')}",
    )
    db.commit()
    findings = store_dayoff_findings(db, row)
    friendly = surgeon_friendly_conflict_message(findings)
    if friendly:
        warnings.append(friendly)
    notify_admins(
        "Pending Request",
        f"{surgeon.full_name} requested {payload.start_date.strftime('%b %-d')} to {payload.end_date.strftime('%b %-d')}.",
        db,
        kind="day_off_request",
        payload={
            "dayOffId": row.id,
            "surgeonId": surgeon.id,
            "startDate": payload.start_date.isoformat(),
            "endDate": payload.end_date.isoformat(),
        },
        require_dayoff_opt_in=True,
    )
    send_native_push_to_surgeon(
        surgeon.id,
        "Days off request pending",
        (
            f"{payload.start_date.strftime('%b %-d')} request sent — overlap/conflict noted; Shannon will review."
            if warnings
            else f"{payload.start_date.strftime('%b %-d')} request sent for approval"
        ),
        db,
        {"type": "day_off", "requestId": row.id},
    )
    return {"ok": True, "request": serialize_day_off(row), "warnings": warnings[:3]}


def update_native_request_off(db: Session, surgeon: Surgeon, dayoff_id: int, payload: NativeRequestOffInput) -> dict:
    row = db.get(DayOff, dayoff_id)
    if not row or row.surgeon_id != surgeon.id:
        raise HTTPException(404, "Days off request not found")

    _validate_request_dates(payload.start_date, payload.end_date, "changed")
    segments, start_t, end_t = _request_segments(payload)

    warnings: list[str] = []
    overlap_note = day_off_overlap_advisory(
        db,
        surgeon.id,
        payload.start_date,
        payload.end_date,
        exclude_id=row.id,
    )
    if overlap_note:
        warnings.append(overlap_note)

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
    log_schedule_change(
        db,
        event_type="day_off_updated",
        surgeon_id=surgeon.id,
        event_date=payload.start_date,
        title="Time off request updated",
        body=f"{surgeon.initials}: {payload.start_date.strftime('%b %-d')} to {payload.end_date.strftime('%b %-d')}",
    )
    db.commit()
    findings = store_dayoff_findings(db, row)
    friendly = surgeon_friendly_conflict_message(findings)
    if friendly:
        warnings.append(friendly)
    notify_admins(
        "Pending Request updated",
        f"{surgeon.full_name} updated request {payload.start_date.strftime('%b %-d')} to {payload.end_date.strftime('%b %-d')}.",
        db,
        kind="day_off_request",
        payload={"dayOffId": row.id, "surgeonId": surgeon.id},
        require_dayoff_opt_in=True,
    )
    send_native_push_to_surgeon(
        surgeon.id,
        "Days off request updated",
        (
            f"{payload.start_date.strftime('%b %-d')} request updated — overlap noted; Shannon will review."
            if warnings
            else f"{payload.start_date.strftime('%b %-d')} request updated and pending approval"
        ),
        db,
        {"type": "day_off", "requestId": row.id},
    )
    return {"ok": True, "request": serialize_day_off(row), "warnings": warnings[:3]}


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


def _validate_request_dates(start_date, end_date, action: str) -> None:
    validate_request_dates(start_date, end_date, action)


def _request_segments(payload: NativeRequestOffInput):
    return request_segments(payload)
