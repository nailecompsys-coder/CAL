"""Native surgeon OTP login routes."""
import hashlib
import random
import re
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import func as sql_func
from sqlalchemy.orm import Session

from ..auth import create_surgeon_session_token
from ..database import get_db
from ..device_names import readable_device_name
from ..email_service import send_email
from ..models import AdminUser, MagicLink, Surgeon, SurgeonDevice, SurgeonOtpAuditLog
from ..sms_service import generate_sms_otp
from ..surgeon_visibility import surgeon_is_visible

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


def _digits_only(value: str | None) -> str:
    return re.sub(r"\D+", "", value or "")


def _canonical_phone_digits(value: str | None) -> str:
    digits = _digits_only(value)
    if len(digits) == 11 and digits.startswith("1"):
        return digits[1:]
    return digits


def _find_active_surgeon_by_email(db: Session, email: str) -> Surgeon | None:
    surgeon = db.query(Surgeon).filter(
        sql_func.lower(Surgeon.email) == email.strip().lower(),
        Surgeon.is_active == True,  # noqa: E712
    ).first()
    return surgeon if surgeon_is_visible(surgeon) else None


def _find_active_surgeon_by_phone(db: Session, phone: str) -> Surgeon | None:
    target = _canonical_phone_digits(phone)
    if len(target) != 10:
        return None

    candidates = db.query(Surgeon).filter(
        Surgeon.is_active == True,  # noqa: E712
        Surgeon.phone.isnot(None),
    ).all()
    matches = [surgeon for surgeon in candidates if surgeon_is_visible(surgeon) and _canonical_phone_digits(surgeon.phone) == target]
    if len(matches) != 1:
        return None
    return matches[0]


def _find_active_surgeon_by_identifier(db: Session, identifier: str) -> Surgeon | None:
    submitted = identifier.strip()
    if "@" in submitted:
        return _find_active_surgeon_by_email(db, submitted)
    return _find_active_surgeon_by_phone(db, submitted)


def _find_active_admin_by_identifier(db: Session, identifier: str) -> AdminUser | None:
    submitted = identifier.strip()
    if "@" not in submitted:
        return None

    admin = db.query(AdminUser).filter(
        sql_func.lower(AdminUser.email) == submitted.lower(),
        AdminUser.is_active == True,  # noqa: E712
    ).first()
    return admin


def _find_admin_preview_surgeon(db: Session) -> Surgeon | None:
    candidates = (
        db.query(Surgeon)
        .filter(
            Surgeon.is_active == True,  # noqa: E712
            Surgeon.staff_type == "physician",
        )
        .order_by(Surgeon.sort_order, Surgeon.id)
        .all()
    )
    return next((surgeon for surgeon in candidates if surgeon_is_visible(surgeon)), None)


def _admin_preview_phone(db: Session, admin: AdminUser) -> str | None:
    contact = db.query(Surgeon).filter(
        sql_func.lower(Surgeon.email) == admin.email.lower(),
        Surgeon.phone.isnot(None),
    ).first()
    return contact.phone if contact else None


def _resolve_native_login_identity(db: Session, identifier: str) -> tuple[Surgeon | None, AdminUser | None]:
    surgeon = _find_active_surgeon_by_identifier(db, identifier)
    if surgeon:
        return surgeon, None

    admin = _find_active_admin_by_identifier(db, identifier)
    if not admin:
        return None, None
    return _find_admin_preview_surgeon(db), admin


def _invalidate_existing_otp_codes(db: Session, surgeon_id: int) -> None:
    db.query(MagicLink).filter(
        MagicLink.surgeon_id == surgeon_id,
        MagicLink.used_at.is_(None),
        MagicLink.token_hash.like("%:otp"),
    ).delete(synchronize_session=False)


def _create_native_session_device(surgeon_id: int, user_agent: str, now: datetime) -> SurgeonDevice:
    return SurgeonDevice(
        surgeon_id=surgeon_id,
        device_name=readable_device_name(None, user_agent),
        user_agent=user_agent,
        token_hash=hashlib.sha256(f"{surgeon_id}:{now.isoformat()}".encode()).hexdigest(),
        is_active=True,
    )


def _send_otp_email(surgeon: Surgeon, code: str, to_email: str | None = None) -> tuple[bool, str | None]:
    recipient = to_email or surgeon.email
    try:
        sent = send_email(
            to_email=recipient,
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
        if sent:
            return True, None
        return False, "Email service is not configured or failed to send code."
    except Exception as exc:
        return False, f"Email send failed: {exc.__class__.__name__}"


def _otp_sms_message_template() -> str:
    return f"CAL access code: $OTP\nExpires in {OTP_EXPIRE_MINUTES} min. Do not share."


def _textbelt_otp_userid(surgeon: Surgeon) -> str:
    return f"cal:surgeon:{surgeon.id}"


def _textbelt_admin_otp_userid(admin: AdminUser) -> str:
    return f"cal:admin:{admin.id}"


def _client_ip(request: Request) -> str | None:
    forwarded_for = request.headers.get("x-forwarded-for", "")
    if forwarded_for:
        return forwarded_for.split(",", 1)[0].strip()
    if request.client:
        return request.client.host
    return None


def _audit_otp(
    db: Session,
    *,
    request: Request,
    action: str,
    submitted_email: str,
    surgeon: Surgeon | None,
    delivery_channel: str | None,
    delivery_success: bool | None,
    result: str,
    failure_reason: str | None = None,
) -> None:
    db.add(SurgeonOtpAuditLog(
        action=action,
        submitted_email=submitted_email.strip().lower(),
        surgeon_id=surgeon.id if surgeon else None,
        matched=surgeon is not None,
        delivery_channel=delivery_channel,
        delivery_success=delivery_success,
        result=result,
        failure_reason=failure_reason,
        client_ip=_client_ip(request),
        user_agent=request.headers.get("User-Agent", "CAL Native App"),
    ))


@router.post("/otp/request")
def otp_request(body: OtpRequestBody, request: Request, db: Session = Depends(get_db)):
    submitted_identifier = body.email.strip().lower()
    surgeon, admin_preview = _resolve_native_login_identity(db, submitted_identifier)
    if not surgeon:
        # Don't reveal whether email exists
        _audit_otp(
            db,
            request=request,
            action="request",
            submitted_email=submitted_identifier,
            surgeon=None,
            delivery_channel="none",
            delivery_success=False,
            result="invalid_email",
            failure_reason="No active surgeon matched submitted email or phone.",
        )
        db.commit()
        return {"ok": True, "message": "If that email or phone is registered, a code was sent."}

    admin_preview_phone = _admin_preview_phone(db, admin_preview) if admin_preview else None
    delivery_channel = "sms+email" if admin_preview_phone or (surgeon.phone and not admin_preview) else "email"
    delivery_success = False
    failure_reasons = []
    code = _generate_otp()

    if admin_preview_phone and admin_preview:
        sms_success, sms_code, sms_failure = generate_sms_otp(
            phone=admin_preview_phone,
            userid=_textbelt_admin_otp_userid(admin_preview),
            message=_otp_sms_message_template(),
            lifetime=OTP_EXPIRE_MINUTES * 60,
            length=6,
        )
        if sms_success and sms_code:
            code = sms_code
        elif sms_failure:
            failure_reasons.append(sms_failure)
        else:
            failure_reasons.append("SMS provider failed to send code.")
        delivery_success = sms_success
    elif surgeon.phone and not admin_preview:
        sms_success, sms_code, sms_failure = generate_sms_otp(
            phone=surgeon.phone,
            userid=_textbelt_otp_userid(surgeon),
            message=_otp_sms_message_template(),
            lifetime=OTP_EXPIRE_MINUTES * 60,
            length=6,
        )
        if sms_success and sms_code:
            code = sms_code
        elif sms_failure:
            failure_reasons.append(sms_failure)
        else:
            failure_reasons.append("SMS provider failed to send code.")
        delivery_success = sms_success

    _invalidate_existing_otp_codes(db, surgeon.id)
    db.add(MagicLink(
        surgeon_id=surgeon.id,
        token_hash=_hash_otp(code) + ":otp",
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=OTP_EXPIRE_MINUTES),
    ))
    db.commit()

    email_success, email_failure = _send_otp_email(surgeon, code, to_email=admin_preview.email if admin_preview else None)
    if email_failure:
        failure_reasons.append(email_failure)
    delivery_success = delivery_success or email_success
    failure_reason = " ".join(failure_reasons) if failure_reasons and not delivery_success else None

    _audit_otp(
        db,
        request=request,
        action="request",
        submitted_email=submitted_identifier,
        surgeon=surgeon,
        delivery_channel=delivery_channel,
        delivery_success=delivery_success,
        result="requested" if delivery_success else "delivery_failed",
        failure_reason=failure_reason,
    )
    db.commit()
    return {"ok": True, "message": "If that email or phone is registered, a code was sent."}


@router.post("/otp/verify")
def otp_verify(body: OtpVerifyBody, request: Request, db: Session = Depends(get_db)):
    submitted_identifier = body.email.strip().lower()
    surgeon, _admin_preview_email = _resolve_native_login_identity(db, submitted_identifier)
    if not surgeon:
        _audit_otp(
            db,
            request=request,
            action="verify",
            submitted_email=submitted_identifier,
            surgeon=None,
            delivery_channel="none",
            delivery_success=False,
            result="invalid_email",
            failure_reason="No active surgeon matched submitted email or phone.",
        )
        db.commit()
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
        _audit_otp(
            db,
            request=request,
            action="verify",
            submitted_email=submitted_identifier,
            surgeon=surgeon,
            delivery_channel="none",
            delivery_success=False,
            result="invalid_code",
            failure_reason="No unused, unexpired OTP matched submitted code.",
        )
        db.commit()
        raise HTTPException(status_code=401, detail="Invalid or expired code")

    link.used_at = now
    ua = request.headers.get("User-Agent", "CAL Native App")
    device = _create_native_session_device(surgeon.id, ua, now)
    db.add(device)
    db.flush()

    jwt_token = create_surgeon_session_token(device.id)
    _audit_otp(
        db,
        request=request,
        action="verify",
        submitted_email=submitted_identifier,
        surgeon=surgeon,
        delivery_channel="none",
        delivery_success=True,
        result="verified",
    )
    db.commit()

    return {"token": jwt_token}
