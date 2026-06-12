"""Native surgeon OTP login routes."""
import hashlib
import random
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import func as sql_func
from sqlalchemy.orm import Session

from ..auth import create_surgeon_session_token
from ..database import get_db
from ..email_service import send_email
from ..models import MagicLink, Surgeon, SurgeonDevice
from ..sms_service import send_sms

router = APIRouter()

OTP_EXPIRE_MINUTES = 15


def _generate_otp() -> str:
    return str(random.randint(100000, 999999))


def _hash_otp(code: str) -> str:
    return hashlib.sha256(code.encode()).hexdigest()


class OtpRequestBody(BaseModel):
    email: str


class OtpVerifyBody(BaseModel):
    email: str
    code: str


def _find_active_surgeon_by_email(db: Session, email: str) -> Surgeon | None:
    return db.query(Surgeon).filter(
        sql_func.lower(Surgeon.email) == email.strip().lower(),
        Surgeon.is_active == True,  # noqa: E712
    ).first()


def _invalidate_existing_otp_codes(db: Session, surgeon_id: int) -> None:
    db.query(MagicLink).filter(
        MagicLink.surgeon_id == surgeon_id,
        MagicLink.used_at.is_(None),
        MagicLink.token_hash.like("%:otp"),
    ).delete(synchronize_session=False)


def _create_native_session_device(surgeon_id: int, user_agent: str, now: datetime) -> SurgeonDevice:
    return SurgeonDevice(
        surgeon_id=surgeon_id,
        device_name=user_agent[:128],
        user_agent=user_agent,
        token_hash=hashlib.sha256(f"{surgeon_id}:{now.isoformat()}".encode()).hexdigest(),
        is_active=True,
    )


@router.post("/otp/request")
def otp_request(body: OtpRequestBody, db: Session = Depends(get_db)):
    surgeon = _find_active_surgeon_by_email(db, body.email)
    if not surgeon:
        # Don't reveal whether email exists
        return {"ok": True, "message": "If that email is registered, a code was sent."}

    code = _generate_otp()
    _invalidate_existing_otp_codes(db, surgeon.id)

    db.add(MagicLink(
        surgeon_id=surgeon.id,
        token_hash=_hash_otp(code) + ":otp",
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=OTP_EXPIRE_MINUTES),
    ))
    db.commit()

    if surgeon.phone:
        send_sms(
            phone=surgeon.phone,
            message=f"CAL access code: {code}\nExpires in {OTP_EXPIRE_MINUTES} min. Do not share.",
        )
    else:
        send_email(
            to_email=surgeon.email,
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
    return {"ok": True, "message": "If that email is registered, a code was sent."}


@router.post("/otp/verify")
def otp_verify(body: OtpVerifyBody, request: Request, db: Session = Depends(get_db)):
    surgeon = _find_active_surgeon_by_email(db, body.email)
    if not surgeon:
        raise HTTPException(status_code=401, detail="Invalid code")

    code = body.code.strip()
    token_hash = _hash_otp(code) + ":otp"
    now = datetime.now(timezone.utc)

    link = db.query(MagicLink).filter(
        MagicLink.surgeon_id == surgeon.id,
        MagicLink.token_hash == token_hash,
        MagicLink.used_at.is_(None),
        MagicLink.expires_at > now,
    ).first()

    if not link:
        raise HTTPException(status_code=401, detail="Invalid or expired code")

    link.used_at = now
    ua = request.headers.get("User-Agent", "CAL Native App")
    device = _create_native_session_device(surgeon.id, ua, now)
    db.add(device)
    db.flush()

    jwt_token = create_surgeon_session_token(device.id)
    db.commit()

    return {"token": jwt_token}
