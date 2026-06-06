from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException
from sqlalchemy.orm import Session

from .auth_tokens import MAGIC_LINK_EXPIRE_HOURS
from .models import MagicLink, SurgeonDevice


def generate_magic_link_token(surgeon_id: int, db: Session, base_url: str) -> str:
    """Creates a magic link record and returns the full URL."""
    raw_token = secrets.token_urlsafe(48)
    token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
    expires_at = datetime.now(timezone.utc) + timedelta(hours=MAGIC_LINK_EXPIRE_HOURS)

    link = MagicLink(surgeon_id=surgeon_id, token_hash=token_hash, expires_at=expires_at)
    db.add(link)
    db.commit()
    return f"{base_url}/register?token={raw_token}"


def redeem_magic_link(raw_token: str, user_agent: str, db: Session) -> SurgeonDevice:
    """Validates magic link and creates a persistent device record."""
    token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
    now = datetime.now(timezone.utc)

    link = db.query(MagicLink).filter(
        MagicLink.token_hash == token_hash,
        MagicLink.used_at.is_(None),
        MagicLink.expires_at > now,
    ).first()

    if not link:
        raise HTTPException(status_code=400, detail="Invalid or expired registration link.")

    link.used_at = now
    device_token_hash = hashlib.sha256(secrets.token_urlsafe(64).encode()).hexdigest()
    device = SurgeonDevice(
        surgeon_id=link.surgeon_id,
        device_name=parse_device_name(user_agent),
        user_agent=user_agent,
        token_hash=device_token_hash,
        last_seen=now,
    )
    db.add(device)
    db.commit()
    db.refresh(device)
    return device


def parse_device_name(ua: str) -> str:
    ua_lower = ua.lower()
    if "iphone" in ua_lower:
        return "iPhone"
    if "ipad" in ua_lower:
        return "iPad"
    if "android" in ua_lower:
        return "Android"
    if "macintosh" in ua_lower or "mac os" in ua_lower:
        return "Mac"
    if "windows" in ua_lower:
        return "Windows PC"
    return "Unknown Device"
