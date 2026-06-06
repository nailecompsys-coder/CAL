"""Native iOS API endpoints."""
from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..auth import get_current_surgeon
from ..conflicts import check_conflicts
from ..database import get_db
from ..native_availability_service import save_native_availability as save_native_availability_service
from ..native_call_coverage_service import assign_native_call_coverage, cancel_native_call_coverage
from ..native_home_service import build_native_home
from ..native_misc_service import mark_alerts_read, save_push_token
from ..native_request_off_service import (
    NativeRequestOffInput,
    cancel_native_request_off as cancel_native_request_off_service,
    create_native_request_off,
    update_native_request_off,
)
from ..native_surgery_notes_service import save_native_surgery_notes as save_native_surgery_notes_service
from ..push import send_native_push_to_surgeon
from .api_common import parse_iso_date_range

router = APIRouter(prefix="/api/native")


@router.get("/home")
def native_home(
    start: str,
    end: str,
    db: Session = Depends(get_db),
    auth=Depends(get_current_surgeon),
):
    surgeon, _ = auth
    start_date, end_date = parse_iso_date_range(start, end)
    return build_native_home(db, surgeon, start_date, end_date)


@router.post("/alerts/read")
def native_mark_alerts_read(
    db: Session = Depends(get_db),
    auth=Depends(get_current_surgeon),
):
    surgeon, _ = auth
    return mark_alerts_read(db, surgeon.id)


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
    return save_native_availability_service(db, surgeon, body.days, check_conflicts)


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
    return save_native_surgery_notes_service(db, surgeon, case_id, body.notes, send_native_push_to_surgeon)


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
    return save_push_token(db, surgeon, device, token, body.platform)
