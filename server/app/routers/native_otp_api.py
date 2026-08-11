"""Unified native OTP login — resolves surgeon and/or scheduler without client role toggle."""

from __future__ import annotations

import hashlib
import os
import random
import re
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import func as sql_func
from sqlalchemy.orm import Session

from ..auth import create_native_scheduler_token, create_surgeon_session_token
from ..database import get_db
from ..device_names import readable_device_name
from ..email_service import send_email
from ..models import AdminOtpChallenge, AdminUser, MagicLink, Surgeon, SurgeonDevice
from ..sms_service import generate_sms_otp
from ..surgeon_visibility import surgeon_is_visible

router = APIRouter(prefix="/api/native")

OTP_EXPIRE_MINUTES = 15
_SCHEDULER_ROLES = frozenset({"scheduler", "admin", "superadmin"})


class NativeOtpRequestBody(BaseModel):
    email: str


class NativeOtpVerifyBody(BaseModel):
    email: str
    code: str


def _generate_otp() -> str:
    return str(random.randint(100000, 999999))


def _hash_otp(code: str) -> str:
    return hashlib.sha256(code.encode()).hexdigest()


def _digits_only(value: str | None) -> str:
    return re.sub(r"\D+", "", value or "")


def _canonical_phone_digits(value: str | None) -> str:
    digits = _digits_only(value)
    if len(digits) == 11 and digits.startswith("1"):
        return digits[1:]
    return digits


def _local_dev_otp() -> str | None:
    for key in ("CAL_LOCAL_DEV_SURGEON_OTP", "CAL_LOCAL_DEV_SCHEDULER_OTP"):
        value = os.environ.get(key, "").strip()
        if value.isdigit() and len(value) == 6:
            return value
    return None


def _find_active_surgeon_by_email(db: Session, email: str) -> Surgeon | None:
    # Auth lookup: active surgeons may sign in even if roster-hidden (e.g. Don dual login).
    return db.query(Surgeon).filter(
        sql_func.lower(Surgeon.email) == email.strip().lower(),
        Surgeon.is_active == True,  # noqa: E712
    ).first()


def _find_active_surgeon_by_phone(db: Session, phone: str) -> Surgeon | None:
    target = _canonical_phone_digits(phone)
    if len(target) != 10:
        return None
    candidates = db.query(Surgeon).filter(
        Surgeon.is_active == True,  # noqa: E712
        Surgeon.phone.isnot(None),
    ).all()
    # Prefer a unique visible match; fall back to unique active match for dual-login accounts.
    visible = [
        surgeon
        for surgeon in candidates
        if surgeon_is_visible(surgeon) and _canonical_phone_digits(surgeon.phone) == target
    ]
    if len(visible) == 1:
        return visible[0]
    matches = [surgeon for surgeon in candidates if _canonical_phone_digits(surgeon.phone) == target]
    if len(matches) != 1:
        return None
    return matches[0]


def _find_active_surgeon(db: Session, identifier: str) -> Surgeon | None:
    submitted = identifier.strip()
    if "@" in submitted:
        return _find_active_surgeon_by_email(db, submitted)
    return _find_active_surgeon_by_phone(db, submitted)


def _find_scheduler_admin(db: Session, identifier: str) -> AdminUser | None:
    submitted = identifier.strip()
    if "@" not in submitted:
        return None
    admin = db.query(AdminUser).filter(
        sql_func.lower(AdminUser.email) == submitted.lower(),
        AdminUser.is_active == True,  # noqa: E712
    ).first()
    if admin and admin.role in _SCHEDULER_ROLES:
        return admin
    return None


def _resolve_identities(db: Session, identifier: str) -> tuple[Surgeon | None, AdminUser | None]:
    return _find_active_surgeon(db, identifier), _find_scheduler_admin(db, identifier)


def _invalidate_surgeon_otps(db: Session, surgeon_id: int) -> None:
    db.query(MagicLink).filter(
        MagicLink.surgeon_id == surgeon_id,
        MagicLink.used_at.is_(None),
        MagicLink.token_hash.like("%:otp"),
    ).delete(synchronize_session=False)


def _store_surgeon_otp(db: Session, surgeon_id: int, code: str, expires_at: datetime) -> MagicLink:
    token_hash = _hash_otp(code) + ":otp"
    _invalidate_surgeon_otps(db, surgeon_id)
    db.query(MagicLink).filter(MagicLink.token_hash == token_hash).delete(synchronize_session=False)
    link = MagicLink(
        surgeon_id=surgeon_id,
        token_hash=token_hash,
        expires_at=expires_at,
    )
    db.add(link)
    return link


def _store_admin_otp(db: Session, admin_id: int, code: str, expires_at: datetime) -> AdminOtpChallenge:
    db.query(AdminOtpChallenge).filter(
        AdminOtpChallenge.admin_user_id == admin_id,
        AdminOtpChallenge.used_at.is_(None),
    ).delete(synchronize_session=False)
    challenge = AdminOtpChallenge(
        admin_user_id=admin_id,
        token_hash=_hash_otp(code),
        expires_at=expires_at,
    )
    db.add(challenge)
    return challenge


def _send_access_email(to_email: str, code: str) -> bool:
    return bool(
        send_email(
            to_email=to_email,
            subject="Your CAL access code",
            html_body=f"""
            <div style="font-family:sans-serif;max-width:480px;margin:0 auto;padding:32px">
              <h2 style="color:#2A3F54;margin-bottom:8px">CAL Access Code</h2>
              <p style="color:#6B7C93;margin-bottom:24px">Mid Florida Surgical Associates</p>
              <div style="background:#f8fafc;border:1px solid #e2e8f0;border-radius:16px;padding:32px;text-align:center">
                <p style="font-size:48px;font-weight:700;letter-spacing:12px;color:#2A3F54;margin:0">{code}</p>
              </div>
              <p style="color:#6B7C93;font-size:13px;margin-top:20px">
                This code expires in {OTP_EXPIRE_MINUTES} minutes. Do not share it with anyone.
              </p>
            </div>
            """,
        )
    )


def _create_surgeon_device(surgeon_id: int, user_agent: str, now: datetime) -> SurgeonDevice:
    return SurgeonDevice(
        surgeon_id=surgeon_id,
        device_name=readable_device_name(None, user_agent),
        user_agent=user_agent,
        token_hash=hashlib.sha256(f"{surgeon_id}:{now.isoformat()}".encode()).hexdigest(),
        is_active=True,
    )


def _issue_surgeon_token(db: Session, surgeon: Surgeon, request: Request, now: datetime) -> str:
    device = _create_surgeon_device(surgeon.id, request.headers.get("User-Agent", "CAL Native App"), now)
    db.add(device)
    db.flush()
    return create_surgeon_session_token(device.id)


@router.post("/otp/request")
def native_otp_request(body: NativeOtpRequestBody, db: Session = Depends(get_db)):
    submitted = body.email.strip().lower()
    surgeon, admin = _resolve_identities(db, submitted)
    if not surgeon and not admin:
        return {"ok": True, "message": "If that account is registered, a code was sent.", "roles": []}

    local_dev_code = _local_dev_otp()
    code = local_dev_code or _generate_otp()
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=OTP_EXPIRE_MINUTES)
    sent = bool(local_dev_code)
    roles: list[str] = []

    if surgeon:
        roles.append("surgeon")
        _store_surgeon_otp(db, surgeon.id, code, expires_at)
    if admin:
        roles.append("scheduler")
        _store_admin_otp(db, admin.id, code, expires_at)

    if not local_dev_code:
        phone = None
        sms_userid = None
        if admin and admin.phone:
            phone = admin.phone
            sms_userid = f"cal:scheduler:{admin.id}"
        elif surgeon and surgeon.phone:
            phone = surgeon.phone
            sms_userid = f"cal:surgeon:{surgeon.id}"

        if phone and sms_userid:
            sms_success, sms_code, _ = generate_sms_otp(
                phone=phone,
                userid=sms_userid,
                message=f"CAL access code: $OTP\nExpires in {OTP_EXPIRE_MINUTES} min. Do not share.",
                lifetime=OTP_EXPIRE_MINUTES * 60,
                length=6,
            )
            if sms_success and sms_code:
                code = sms_code
                # Re-store with Textbelt-issued code so verify matches.
                if surgeon:
                    _store_surgeon_otp(db, surgeon.id, code, expires_at)
                if admin:
                    _store_admin_otp(db, admin.id, code, expires_at)
            sent = sms_success or sent

        email_to = (admin.email if admin else None) or (surgeon.email if surgeon else None)
        if email_to:
            sent = _send_access_email(email_to, code) or sent

    db.commit()

    # Unknown accounts stay vague above (anti-enumeration). Known account + delivery
    # failure must not pretend a code was sent.
    if not sent:
        raise HTTPException(
            status_code=503,
            detail="Could not send a code. Try again or contact the office.",
        )

    message = (
        f"Local access code: {local_dev_code}"
        if local_dev_code
        else "Check your email or iPhone for the CAL access code."
    )
    return {
        "ok": True,
        "message": message,
        "sent": True,
        "roles": roles,
        "devCode": local_dev_code,
    }


@router.post("/otp/verify")
def native_otp_verify(body: NativeOtpVerifyBody, request: Request, db: Session = Depends(get_db)):
    submitted = body.email.strip().lower()
    code = body.code.strip()
    surgeon, admin = _resolve_identities(db, submitted)
    if not surgeon and not admin:
        raise HTTPException(401, "Invalid code")

    local_dev_code = _local_dev_otp()
    now = datetime.now(timezone.utc)
    code_ok = bool(local_dev_code and code == local_dev_code)

    surgeon_token: str | None = None
    scheduler_token: str | None = None
    roles: list[str] = []

    if surgeon:
        token_hash = _hash_otp(code) + ":otp"
        link = db.query(MagicLink).filter(
            MagicLink.surgeon_id == surgeon.id,
            MagicLink.token_hash == token_hash,
            MagicLink.used_at.is_(None),
            MagicLink.expires_at > now,
        ).first()
        if not link and local_dev_code and code == local_dev_code:
            link = _store_surgeon_otp(db, surgeon.id, code, now + timedelta(minutes=OTP_EXPIRE_MINUTES))
            db.flush()
        if link:
            link.used_at = now
            surgeon_token = _issue_surgeon_token(db, surgeon, request, now)
            roles.append("surgeon")
            code_ok = True

    if admin:
        challenge = db.query(AdminOtpChallenge).filter(
            AdminOtpChallenge.admin_user_id == admin.id,
            AdminOtpChallenge.token_hash == _hash_otp(code),
            AdminOtpChallenge.used_at.is_(None),
            AdminOtpChallenge.expires_at > now,
        ).first()
        if challenge or (local_dev_code and code == local_dev_code):
            if challenge:
                challenge.used_at = now
            scheduler_token = create_native_scheduler_token(admin.id)
            roles.append("scheduler")
            code_ok = True

    if not code_ok or not roles:
        raise HTTPException(401, "Invalid or expired code")

    db.commit()

    # Prefer surgeon as the active shell when dual — schedule is the daily default.
    if "surgeon" in roles and surgeon_token:
        primary_role = "surgeon"
        primary_token = surgeon_token
    else:
        primary_role = "scheduler"
        primary_token = scheduler_token

    return {
        "token": primary_token,
        "role": primary_role,
        "roles": roles,
        "tokens": {
            "surgeon": surgeon_token,
            "scheduler": scheduler_token,
        },
        "identity": {
            "surgeon_id": surgeon.id if surgeon and "surgeon" in roles else None,
            "admin_id": admin.id if admin and "scheduler" in roles else None,
            "email": submitted,
        },
    }
