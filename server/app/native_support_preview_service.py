"""Audited, short-lived read-only native schedule preview for admins."""

import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from jose import JWTError, jwt
from sqlalchemy.orm import Session

from .auth_tokens import ALGORITHM, SECRET_KEY
from .models import AdminUser, NativeSupportPreviewGrant, Surgeon
from .surgeon_visibility import surgeon_is_visible

CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
CODE_MINUTES = 10
SESSION_MINUTES = 30


def _normalize_code(code: str) -> str:
    return "".join(char for char in code.upper() if char in CODE_ALPHABET)


def _hash_code(code: str) -> str:
    return hashlib.sha256(code.encode("ascii")).hexdigest()


def issue_preview_code(db: Session, admin: AdminUser, surgeon_id: int) -> str | None:
    if admin.role not in {"admin", "superadmin"} or not admin.is_active:
        return None
    surgeon = db.get(Surgeon, surgeon_id)
    if not surgeon_is_visible(surgeon):
        return None

    code = "".join(secrets.choice(CODE_ALPHABET) for _ in range(12))
    db.add(NativeSupportPreviewGrant(
        admin_user_id=admin.id,
        surgeon_id=surgeon_id,
        code_hash=_hash_code(code),
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=CODE_MINUTES),
    ))
    db.commit()
    return "-".join(code[index:index + 4] for index in (0, 4, 8))


def redeem_preview_code(db: Session, code: str, client_ip: str | None) -> tuple[str, Surgeon] | None:
    normalized = _normalize_code(code)
    if len(normalized) != 12:
        return None
    now = datetime.now(timezone.utc)
    grant = (
        db.query(NativeSupportPreviewGrant)
        .filter(
            NativeSupportPreviewGrant.code_hash == _hash_code(normalized),
            NativeSupportPreviewGrant.redeemed_at.is_(None),
            NativeSupportPreviewGrant.expires_at > now,
        )
        .with_for_update()
        .one_or_none()
    )
    if not grant or not grant.admin_user.is_active or grant.admin_user.role not in {"admin", "superadmin"}:
        return None
    surgeon = grant.surgeon
    if not surgeon_is_visible(surgeon):
        return None

    grant.redeemed_at = now
    grant.redeemed_ip = (client_ip or "")[:64]
    token = jwt.encode({
        "sub": str(surgeon.id),
        "admin_id": grant.admin_user_id,
        "grant_id": grant.id,
        "type": "native_support_preview",
        "exp": now + timedelta(minutes=SESSION_MINUTES),
    }, SECRET_KEY, algorithm=ALGORITHM)
    db.commit()
    return token, surgeon


def surgeon_for_preview_token(db: Session, token: str) -> Surgeon | None:
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        if payload.get("type") != "native_support_preview":
            return None
        surgeon_id = int(payload["sub"])
        admin_id = int(payload["admin_id"])
        grant_id = int(payload["grant_id"])
    except (JWTError, KeyError, TypeError, ValueError):
        return None

    grant = db.get(NativeSupportPreviewGrant, grant_id)
    if not grant or not grant.redeemed_at or grant.surgeon_id != surgeon_id or grant.admin_user_id != admin_id:
        return None
    if not grant.admin_user.is_active or grant.admin_user.role not in {"admin", "superadmin"}:
        return None
    surgeon = db.get(Surgeon, surgeon_id)
    return surgeon if surgeon_is_visible(surgeon) else None
