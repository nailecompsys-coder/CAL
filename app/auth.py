from datetime import datetime, timezone

from fastapi import Cookie, Depends, Request
from jose import JWTError
from sqlalchemy.orm import Session

from .auth_request import raise_html_or_json_auth_error, request_wants_json
from .auth_tokens import (
    ADMIN_TOKEN_EXPIRE_HOURS,
    ALGORITHM,
    SECRET_KEY,
    SURGEON_TOKEN_EXPIRE_DAYS,
    cookie_secure,
    create_admin_token,
    create_surgeon_session_token,
    decode_subject_token,
    hash_password,
    pwd_context,
    verify_password,
)
from .database import get_db
from .models import AdminUser, Surgeon, SurgeonDevice
from .surgeon_visibility import surgeon_is_visible

# SurgeonDevice.device_name for admin “preview mobile on desktop” sessions.
SURGEON_ADMIN_PREVIEW_DEVICE_NAME = "Admin desktop preview"


def _decode_subject_token(token: str, expected_type: str) -> int:
    return decode_subject_token(token, expected_type)


def _request_wants_json(request: Request) -> bool:
    return request_wants_json(request)


def _raise_html_or_json_auth_error(request: Request, login_path: str) -> None:
    raise_html_or_json_auth_error(request, login_path)


def get_current_admin(
    request: Request,
    admin_token: str | None = Cookie(default=None),
    db: Session = Depends(get_db),
) -> AdminUser:
    token = admin_token or request.cookies.get("admin_token")
    if not token:
        _raise_html_or_json_auth_error(request, "/admin/login")
    try:
        admin_id = _decode_subject_token(token, "admin")
    except (JWTError, ValueError):
        _raise_html_or_json_auth_error(request, "/admin/login")
    admin = db.get(AdminUser, admin_id)
    if not admin or not admin.is_active:
        _raise_html_or_json_auth_error(request, "/admin/login")
    return admin


def get_current_surgeon(
    request: Request,
    surgeon_token: str | None = Cookie(default=None),
    db: Session = Depends(get_db),
) -> tuple[Surgeon, SurgeonDevice]:
    token = (
        surgeon_token
        or request.cookies.get("surgeon_token")
        or request.cookies.get("surgeon_token_preview")
    )
    if not token:
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header[7:].strip()
    if not token:
        token = (request.headers.get("X-CAL-Device-Token") or "").strip()

    if not token:
        _raise_html_or_json_auth_error(request, "/surgeon/register")
    try:
        device_id = _decode_subject_token(token, "surgeon")
    except (JWTError, ValueError):
        _raise_html_or_json_auth_error(request, "/surgeon/register")

    device = db.get(SurgeonDevice, device_id)
    if not device or not device.is_active:
        _raise_html_or_json_auth_error(request, "/surgeon/register")

    device.last_seen = datetime.now(timezone.utc)
    db.commit()

    surgeon = db.get(Surgeon, device.surgeon_id)
    if not surgeon_is_visible(surgeon):
        _raise_html_or_json_auth_error(request, "/surgeon/register")

    return surgeon, device


__all__ = [
    "ADMIN_TOKEN_EXPIRE_HOURS",
    "ALGORITHM",
    "SECRET_KEY",
    "SURGEON_ADMIN_PREVIEW_DEVICE_NAME",
    "SURGEON_TOKEN_EXPIRE_DAYS",
    "cookie_secure",
    "create_admin_token",
    "create_surgeon_session_token",
    "get_current_admin",
    "get_current_surgeon",
    "hash_password",
    "pwd_context",
    "verify_password",
]
