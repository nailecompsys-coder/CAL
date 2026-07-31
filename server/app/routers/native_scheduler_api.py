"""Native scheduler API for Block OR and AH-safe scheduling views."""

from __future__ import annotations

import hashlib
import os
import random
from datetime import datetime, time, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import func as sql_func
from sqlalchemy.orm import Session, joinedload

from ..auth import create_native_scheduler_token, get_current_native_scheduler
from ..database import get_db
from ..email_service import send_email
from ..models import AdminOtpChallenge, AdminUser, Location, ORBlockAssignment, ORBlockInstance
from ..or_block_service import (
    BlockORCreateInput,
    SESSION_DEFAULTS,
    add_case_to_block,
    assign_block,
    candidate_surgeon_rows,
    clear_block_assignment,
    create_or_blocks,
    delete_or_block_instance,
    parse_hhmm,
    remove_block_assignment,
    scheduler_native_home,
    serialize_block_instance,
    session_default_times,
    update_block_assignment,
    update_block_case,
    update_or_block_instance,
)
from ..routers.api_common import parse_iso_date_range
from ..sms_service import generate_sms_otp

router = APIRouter(prefix="/api/native/scheduler")

OTP_EXPIRE_MINUTES = 15


class SchedulerOtpRequestBody(BaseModel):
    email: str


class SchedulerOtpVerifyBody(BaseModel):
    email: str
    code: str


class SchedulerAssignBody(BaseModel):
    surgeon_id: int
    start_time: str | None = None
    case_count: int = 0
    note: str = ""


class SchedulerCreateBlockBody(BaseModel):
    date: str
    location_id: int
    session: str = "am"
    start_time: str | None = None
    end_time: str | None = None
    notes: str = ""
    room_text: str | None = None


class SchedulerUpdateBlockBody(BaseModel):
    location_id: int | None = None
    session: str | None = None
    start_time: str | None = None
    end_time: str | None = None
    notes: str | None = None
    room_text: str | None = None


class SchedulerCaseBody(BaseModel):
    surgeon_id: int
    start_time: str
    end_time: str | None = None
    procedure: str = ""
    patient_name: str = ""


class SchedulerCaseUpdateBody(BaseModel):
    start_time: str | None = None
    end_time: str | None = None
    procedure: str | None = None
    patient_name: str | None = None
    surgeon_id: int | None = None
    target_block_id: int | None = None


def _hash_otp(code: str) -> str:
    return hashlib.sha256(code.encode()).hexdigest()


def _generate_otp() -> str:
    return str(random.randint(100000, 999999))


def _local_dev_scheduler_otp() -> str | None:
    value = os.environ.get("CAL_LOCAL_DEV_SCHEDULER_OTP", "").strip()
    return value if value.isdigit() and len(value) == 6 else None


def _find_scheduler_admin(db: Session, identifier: str) -> AdminUser | None:
    admin = db.query(AdminUser).filter(
        sql_func.lower(AdminUser.email) == identifier.strip().lower(),
        AdminUser.is_active == True,  # noqa: E712
    ).first()
    if admin and admin.role in {"scheduler", "admin", "superadmin"}:
        return admin
    return None


def _send_scheduler_email(admin: AdminUser, code: str) -> bool:
    return bool(send_email(
        to_email=admin.email,
        subject="Your CAL scheduler access code",
        html_body=f"""
        <div style="font-family:sans-serif;max-width:480px;margin:0 auto;padding:32px">
          <h2 style="color:#2A3F54;margin-bottom:8px">CAL Scheduler Code</h2>
          <p style="color:#6B7C93;margin-bottom:24px">Mid Florida Surgical Associates</p>
          <div style="background:#f8fafc;border:1px solid #e2e8f0;border-radius:16px;padding:32px;text-align:center">
            <p style="font-size:48px;font-weight:700;letter-spacing:12px;color:#2A3F54;margin:0">{code}</p>
          </div>
          <p style="color:#6B7C93;font-size:13px;margin-top:20px">This code expires in {OTP_EXPIRE_MINUTES} minutes.</p>
        </div>
        """,
    ))


@router.post("/otp/request")
def scheduler_otp_request(body: SchedulerOtpRequestBody, db: Session = Depends(get_db)):
    submitted = body.email.strip().lower()
    admin = _find_scheduler_admin(db, submitted)
    if not admin:
        return {"ok": True, "scheduler": False, "message": "If that scheduler account is registered, a code was sent."}

    db.query(AdminOtpChallenge).filter(
        AdminOtpChallenge.admin_user_id == admin.id,
        AdminOtpChallenge.used_at.is_(None),
    ).delete(synchronize_session=False)
    local_dev_code = _local_dev_scheduler_otp()
    code = local_dev_code or _generate_otp()
    sent = bool(local_dev_code)
    if admin.phone and not local_dev_code:
        sms_success, sms_code, _ = generate_sms_otp(
            phone=admin.phone,
            userid=f"cal:scheduler:{admin.id}",
            message=f"CAL scheduler code: $OTP\nExpires in {OTP_EXPIRE_MINUTES} min.",
            lifetime=OTP_EXPIRE_MINUTES * 60,
            length=6,
        )
        if sms_success and sms_code:
            code = sms_code
        sent = sms_success
    if not local_dev_code:
        sent = _send_scheduler_email(admin, code) or sent
    db.add(AdminOtpChallenge(
        admin_user_id=admin.id,
        token_hash=_hash_otp(code),
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=OTP_EXPIRE_MINUTES),
    ))
    db.commit()
    return {
        "ok": True,
        "scheduler": True,
        "message": f"Local scheduler code: {local_dev_code}" if local_dev_code else "If that scheduler account is registered, a code was sent.",
        "sent": sent,
        "devCode": local_dev_code,
    }


@router.post("/otp/verify")
def scheduler_otp_verify(body: SchedulerOtpVerifyBody, db: Session = Depends(get_db)):
    admin = _find_scheduler_admin(db, body.email.strip().lower())
    if not admin:
        raise HTTPException(401, "Invalid code")
    local_dev_code = _local_dev_scheduler_otp()
    if local_dev_code and body.code.strip() == local_dev_code:
        return {
            "token": create_native_scheduler_token(admin.id),
            "identity": {
                "id": admin.id,
                "role": admin.role,
                "name": admin.full_name,
                "email": admin.email,
            },
        }
    now = datetime.now(timezone.utc)
    challenge = db.query(AdminOtpChallenge).filter(
        AdminOtpChallenge.admin_user_id == admin.id,
        AdminOtpChallenge.token_hash == _hash_otp(body.code.strip()),
        AdminOtpChallenge.used_at.is_(None),
        AdminOtpChallenge.expires_at > now,
    ).first()
    if not challenge:
        raise HTTPException(401, "Invalid or expired code")
    challenge.used_at = now
    db.commit()
    return {
        "token": create_native_scheduler_token(admin.id),
        "identity": {
            "id": admin.id,
            "role": admin.role,
            "name": admin.full_name,
            "email": admin.email,
        },
    }


@router.get("/home")
def scheduler_home(
    start: str,
    end: str,
    db: Session = Depends(get_db),
    admin=Depends(get_current_native_scheduler),
):
    start_date, end_date = parse_iso_date_range(start, end)
    return scheduler_native_home(db, start_date, end_date)


@router.get("/meta")
def scheduler_meta(
    db: Session = Depends(get_db),
    admin=Depends(get_current_native_scheduler),
):
    hospitals = (
        db.query(Location)
        .filter(Location.is_active == True, Location.location_type == "hospital")  # noqa: E712
        .order_by(Location.name)
        .all()
    )
    sessions = []
    for key in ("am", "pm", "both", "custom"):
        start_t, end_t = SESSION_DEFAULTS[key]
        sessions.append({
            "id": key,
            "label": key.upper() if key != "both" else "Both",
            "start": start_t.strftime("%H:%M"),
            "end": end_t.strftime("%H:%M"),
        })
    return {
        "hospitals": [
            {
                "id": row.id,
                "name": row.name,
                "abbreviation": row.abbreviation or "",
            }
            for row in hospitals
        ],
        "sessions": sessions,
    }


@router.post("/blocks")
def scheduler_create_block(
    body: SchedulerCreateBlockBody,
    db: Session = Depends(get_db),
    admin=Depends(get_current_native_scheduler),
):
    try:
        block_day = datetime.strptime(body.date.strip(), "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(422, "date must be YYYY-MM-DD")
    session = (body.session or "am").strip().lower()
    default_start, default_end = session_default_times(session)
    try:
        start_t = parse_hhmm(body.start_time or "", default_start)
        end_t = parse_hhmm(body.end_time or "", default_end)
        result = create_or_blocks(
            db,
            BlockORCreateInput(
                name="Open Block",
                start_date=block_day,
                end_date=block_day,
                weekdays=[block_day.weekday()],
                location_ids=[body.location_id],
                session=session,
                start_time=start_t,
                end_time=end_t,
                recurrence="once",
                notes=body.notes or "",
                room_text=body.room_text,
            ),
            admin_id=admin.id,
        )
    except ValueError as exc:
        message = str(exc)
        status = 409 if "Duplicate" in message else 422
        raise HTTPException(status, message)
    instances = (
        db.query(ORBlockInstance)
        .options(
            joinedload(ORBlockInstance.location),
            joinedload(ORBlockInstance.assignments).joinedload(ORBlockAssignment.surgeon),
            joinedload(ORBlockInstance.assigned_surgeon),
        )
        .filter(ORBlockInstance.id.in_(result["instance_ids"]))
        .all()
    )
    by_id = {row.id: row for row in instances}
    blocks = [serialize_block_instance(by_id[block_id]) for block_id in result["instance_ids"] if block_id in by_id]
    return {
        "ok": True,
        "created": result["created"],
        "blockIds": result["instance_ids"],
        "blocks": blocks,
    }


@router.patch("/blocks/{block_id:int}")
def scheduler_update_block(
    block_id: int,
    body: SchedulerUpdateBlockBody,
    db: Session = Depends(get_db),
    admin=Depends(get_current_native_scheduler),
):
    start_t = None
    end_t = None
    if body.start_time is not None:
        try:
            start_t = parse_hhmm(body.start_time)
        except ValueError:
            raise HTTPException(422, "start_time must be HH:MM")
    if body.end_time is not None:
        try:
            end_t = parse_hhmm(body.end_time)
        except ValueError:
            raise HTTPException(422, "end_time must be HH:MM")
    try:
        update_or_block_instance(
            db,
            block_id,
            location_id=body.location_id,
            session=body.session,
            start_time=start_t,
            end_time=end_t,
            notes=body.notes,
            room_text=body.room_text,
            admin_id=admin.id,
        )
    except ValueError as exc:
        message = str(exc)
        if "not found" in message.lower():
            raise HTTPException(404, message)
        if "Duplicate" in message:
            raise HTTPException(409, message)
        raise HTTPException(422, message)
    block = (
        db.query(ORBlockInstance)
        .options(
            joinedload(ORBlockInstance.location),
            joinedload(ORBlockInstance.assignments).joinedload(ORBlockAssignment.surgeon),
            joinedload(ORBlockInstance.assigned_surgeon),
        )
        .filter(ORBlockInstance.id == block_id)
        .first()
    )
    return {"ok": True, "block": serialize_block_instance(block), "warnings": []}


@router.delete("/blocks/{block_id:int}")
def scheduler_delete_block(
    block_id: int,
    db: Session = Depends(get_db),
    admin=Depends(get_current_native_scheduler),
):
    try:
        delete_or_block_instance(db, block_id, admin_id=admin.id)
    except ValueError as exc:
        message = str(exc)
        if "not found" in message.lower():
            raise HTTPException(404, message)
        raise HTTPException(409, message)
    return {"ok": True, "deleted": True, "blockId": block_id}


@router.get("/blocks/{block_id:int}")
def scheduler_block_detail(
    block_id: int,
    db: Session = Depends(get_db),
    admin=Depends(get_current_native_scheduler),
):
    block = db.get(ORBlockInstance, block_id)
    if not block:
        raise HTTPException(404, "Block not found")
    candidates = []
    for row in candidate_surgeon_rows(db, block):
        candidates.append({
            "surgeonId": row["surgeon"].id,
            "name": row["surgeon"].full_name,
            "initials": row["surgeon"].initials,
            "status": row["status"],
            "availability": row["availability"],
            "warnings": row["warnings"],
        })
    return {"block": serialize_block_instance(block), "candidates": candidates}


@router.post("/blocks/{block_id:int}/assign")
def scheduler_assign_block(
    block_id: int,
    body: SchedulerAssignBody,
    db: Session = Depends(get_db),
    admin=Depends(get_current_native_scheduler),
):
    assigned_start = None
    if body.start_time:
        try:
            assigned_start = time.fromisoformat(body.start_time)
        except ValueError:
            raise HTTPException(422, "Start time must be HH:MM")
    try:
        block, warnings = assign_block(
            db,
            block_id,
            body.surgeon_id,
            admin.id,
            assigned_start_time=assigned_start,
            case_count=body.case_count,
            assignment_note=body.note,
        )
    except ValueError as exc:
        message = str(exc)
        if "Add a note" in message:
            raise HTTPException(422, message)
        raise HTTPException(409 if "already assigned" in message else 404, message)
    return {"ok": True, "block": serialize_block_instance(block), "warnings": warnings}


@router.post("/blocks/{block_id:int}/assignments/{assignment_id:int}/update")
def scheduler_update_block_assignment(
    block_id: int,
    assignment_id: int,
    body: SchedulerAssignBody,
    db: Session = Depends(get_db),
    admin=Depends(get_current_native_scheduler),
):
    assigned_start = None
    if body.start_time:
        try:
            assigned_start = time.fromisoformat(body.start_time)
        except ValueError:
            raise HTTPException(422, "Start time must be HH:MM")
    try:
        block, warnings = update_block_assignment(
            db,
            block_id,
            assignment_id,
            body.surgeon_id,
            admin.id,
            assigned_start_time=assigned_start,
            case_count=body.case_count,
            assignment_note=body.note,
        )
    except ValueError as exc:
        message = str(exc)
        if "Add a note" in message:
            raise HTTPException(422, message)
        raise HTTPException(409 if "already assigned" in message else 404, message)
    return {"ok": True, "block": serialize_block_instance(block), "warnings": warnings}


@router.post("/blocks/{block_id:int}/assignments/{assignment_id:int}/remove")
def scheduler_remove_block_assignment(
    block_id: int,
    assignment_id: int,
    db: Session = Depends(get_db),
    admin=Depends(get_current_native_scheduler),
):
    try:
        block = remove_block_assignment(db, block_id, assignment_id, admin.id)
    except ValueError as exc:
        raise HTTPException(404, str(exc))
    return {"ok": True, "block": serialize_block_instance(block), "warnings": []}


@router.post("/blocks/{block_id:int}/clear")
def scheduler_clear_block_assignment(
    block_id: int,
    db: Session = Depends(get_db),
    admin=Depends(get_current_native_scheduler),
):
    try:
        block = clear_block_assignment(db, block_id, admin.id)
    except ValueError as exc:
        message = str(exc)
        status = 404 if "not found" in message.lower() else 409
        raise HTTPException(status, message)
    return {"ok": True, "block": serialize_block_instance(block), "warnings": []}


@router.post("/blocks/{block_id:int}/cases")
def scheduler_add_block_case(
    block_id: int,
    body: SchedulerCaseBody,
    db: Session = Depends(get_db),
    admin=Depends(get_current_native_scheduler),
):
    try:
        start_t = parse_hhmm(body.start_time)
    except ValueError:
        raise HTTPException(422, "start_time must be HH:MM")
    end_t = None
    if body.end_time:
        try:
            end_t = parse_hhmm(body.end_time)
        except ValueError:
            raise HTTPException(422, "end_time must be HH:MM")
    try:
        block, warnings = add_case_to_block(
            db,
            block_id,
            body.surgeon_id,
            start_t,
            end_time=end_t,
            procedure=body.procedure or "",
            patient_name=body.patient_name or "",
            admin_id=admin.id,
        )
    except ValueError as exc:
        message = str(exc)
        status = 404 if "not found" in message.lower() else 422
        if "not on this block" in message.lower():
            status = 409
        raise HTTPException(status, message)
    return {"ok": True, "block": serialize_block_instance(block), "warnings": warnings}


@router.post("/blocks/{block_id:int}/cases/{case_id:int}/update")
def scheduler_update_block_case(
    block_id: int,
    case_id: int,
    body: SchedulerCaseUpdateBody,
    db: Session = Depends(get_db),
    admin=Depends(get_current_native_scheduler),
):
    start_t = None
    end_t = None
    if body.start_time is not None:
        try:
            start_t = parse_hhmm(body.start_time)
        except ValueError:
            raise HTTPException(422, "start_time must be HH:MM")
    if body.end_time is not None:
        try:
            end_t = parse_hhmm(body.end_time)
        except ValueError:
            raise HTTPException(422, "end_time must be HH:MM")
    try:
        block, warnings = update_block_case(
            db,
            block_id,
            case_id,
            start_time=start_t,
            end_time=end_t,
            procedure=body.procedure,
            patient_name=body.patient_name,
            surgeon_id=body.surgeon_id,
            target_block_id=body.target_block_id,
            admin_id=admin.id,
        )
    except ValueError as exc:
        message = str(exc)
        status = 404 if "not found" in message.lower() else 422
        raise HTTPException(status, message)
    return {"ok": True, "block": serialize_block_instance(block), "warnings": warnings}
