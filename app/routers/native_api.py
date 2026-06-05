"""Native iOS API endpoints."""
from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..auth import get_current_surgeon
from ..conflicts import check_conflicts
from ..database import get_db
from ..models import Availability, NativePushToken, NativeScheduleAlert, SurgicalCase
from ..native_call_coverage_service import assign_native_call_coverage, cancel_native_call_coverage
from ..native_home_service import build_native_home
from ..native_request_off_service import (
    NativeRequestOffInput,
    cancel_native_request_off as cancel_native_request_off_service,
    create_native_request_off,
    update_native_request_off,
)
from ..native_support import parse_hhmm
from ..push import send_native_push_to_surgeon
from .api import _parse_iso_date_range

router = APIRouter(prefix="/api/native")


@router.get("/home")
def native_home(
    start: str,
    end: str,
    db: Session = Depends(get_db),
    auth=Depends(get_current_surgeon),
):
    surgeon, _ = auth
    start_date, end_date = _parse_iso_date_range(start, end)
    return build_native_home(db, surgeon, start_date, end_date)


@router.post("/alerts/read")
def native_mark_alerts_read(
    db: Session = Depends(get_db),
    auth=Depends(get_current_surgeon),
):
    surgeon, _ = auth
    rows = db.query(NativeScheduleAlert).filter(
        NativeScheduleAlert.surgeon_id == surgeon.id,
        NativeScheduleAlert.read_at.is_(None),
    ).all()
    now = datetime.utcnow()
    for row in rows:
        row.read_at = now
    db.commit()
    return {"ok": True, "count": len(rows)}


class NativeRequestOffBody(BaseModel):
    start_date: date
    end_date: date
    reason: str = ""
    notes: str = ""
    is_full_day: bool = True
    start: str | None = None
    end: str | None = None
    segments: list[dict] | None = None


def _native_request_off_input(body: NativeRequestOffBody) -> NativeRequestOffInput:
    return NativeRequestOffInput(
        start_date=body.start_date,
        end_date=body.end_date,
        reason=body.reason,
        notes=body.notes,
        is_full_day=body.is_full_day,
        start=body.start,
        end=body.end,
        segments=body.segments,
    )


@router.post("/request-off")
def native_request_off(
    body: NativeRequestOffBody,
    db: Session = Depends(get_db),
    auth=Depends(get_current_surgeon),
):
    surgeon, _ = auth
    return create_native_request_off(db, surgeon, _native_request_off_input(body))


@router.put("/request-off/{dayoff_id}")
def native_update_request_off(
    dayoff_id: int,
    body: NativeRequestOffBody,
    db: Session = Depends(get_db),
    auth=Depends(get_current_surgeon),
):
    surgeon, _ = auth
    return update_native_request_off(db, surgeon, dayoff_id, _native_request_off_input(body))


@router.delete("/request-off/{dayoff_id}")
def native_cancel_request_off(
    dayoff_id: int,
    db: Session = Depends(get_db),
    auth=Depends(get_current_surgeon),
):
    surgeon, _ = auth
    return cancel_native_request_off_service(db, surgeon, dayoff_id)


class NativeCallCoverageBody(BaseModel):
    rotation_id: int
    covering_surgeon_id: int | None = None
    notes: str = ""


@router.post("/call-coverage")
def native_call_coverage(
    body: NativeCallCoverageBody,
    db: Session = Depends(get_db),
    auth=Depends(get_current_surgeon),
):
    surgeon, _ = auth
    assignment = assign_native_call_coverage(
        db,
        requesting_surgeon=surgeon,
        rotation_id=body.rotation_id,
        covering_surgeon_id=body.covering_surgeon_id,
        notes=body.notes,
    )
    return {"ok": True, "assignment": assignment}


@router.post("/call-coverage/{coverage_id:int}/cancel")
def native_cancel_call_coverage(
    coverage_id: int,
    db: Session = Depends(get_db),
    auth=Depends(get_current_surgeon),
):
    surgeon, _ = auth
    assignment = cancel_native_call_coverage(db, requesting_surgeon=surgeon, coverage_id=coverage_id)
    return {"ok": True, "assignment": assignment}


class NativeAvailabilityRow(BaseModel):
    date: date
    isAvailable: bool
    start: str | None = None
    end: str | None = None


class NativeAvailabilityBody(BaseModel):
    days: list[NativeAvailabilityRow]


@router.post("/availability")
def native_save_availability(
    body: NativeAvailabilityBody,
    db: Session = Depends(get_db),
    auth=Depends(get_current_surgeon),
):
    surgeon, _ = auth
    warnings = []
    for row in body.days:
        existing = db.query(Availability).filter(
            Availability.surgeon_id == surgeon.id,
            Availability.date == row.date,
        ).first()
        if not row.isAvailable:
            warnings.extend(check_conflicts(
                surgeon.id,
                row.date,
                row.date,
                db,
                target_entity={"type": "availability", "date": row.date},
            ))
        if existing:
            existing.is_available = row.isAvailable
            existing.start_time = parse_hhmm(row.start)
            existing.end_time = parse_hhmm(row.end)
        else:
            db.add(Availability(
                surgeon_id=surgeon.id,
                date=row.date,
                is_available=row.isAvailable,
                start_time=parse_hhmm(row.start),
                end_time=parse_hhmm(row.end),
            ))
    db.commit()
    return {"ok": True, "warnings": warnings[:5]}


class NativeSurgeryNotesBody(BaseModel):
    notes: str = ""


@router.post("/surgical-case/{case_id:int}/notes")
def native_save_surgery_notes(
    case_id: int,
    body: NativeSurgeryNotesBody,
    db: Session = Depends(get_db),
    auth=Depends(get_current_surgeon),
):
    surgeon, _ = auth
    row = db.get(SurgicalCase, case_id)
    if not row or row.surgeon_id != surgeon.id:
        raise HTTPException(404, "Case not found")
    row.surgeon_notes = body.notes.strip() or None
    db.commit()
    send_native_push_to_surgeon(
        surgeon.id,
        "Surgical case notes updated",
        f"{row.date.strftime('%b %-d')} case notes saved",
        db,
        {"type": "surgical_case", "caseId": row.id},
    )
    return {"ok": True}


class NativePushTokenBody(BaseModel):
    token: str
    platform: str = "ios"


@router.post("/push-token")
def native_push_token(
    body: NativePushTokenBody,
    db: Session = Depends(get_db),
    auth=Depends(get_current_surgeon),
):
    surgeon, device = auth
    token = body.token.strip()
    if not token:
        raise HTTPException(400, "Push token is required")
    row = db.query(NativePushToken).filter(NativePushToken.token == token).first()
    if row:
        row.surgeon_id = surgeon.id
        row.device_id = device.id if device else None
        row.platform = body.platform or "ios"
        row.is_active = True
        row.updated_at = datetime.utcnow()
    else:
        db.add(NativePushToken(
            surgeon_id=surgeon.id,
            device_id=device.id if device else None,
            token=token,
            platform=body.platform or "ios",
            is_active=True,
        ))
    db.commit()
    return {"ok": True}
