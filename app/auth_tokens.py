from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

from jose import JWTError, jwt
from passlib.context import CryptContext

SECRET_KEY = os.environ["SECRET_KEY"]
ALGORITHM = "HS256"
ADMIN_TOKEN_EXPIRE_HOURS = 12
SURGEON_TOKEN_EXPIRE_DAYS = 365
MAGIC_LINK_EXPIRE_HOURS = int(os.environ.get("MAGIC_LINK_EXPIRE_HOURS", "168"))

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def cookie_secure() -> bool:
    """Set COOKIE_SECURE=false for local http:// dev (default: secure cookies on)."""
    return os.environ.get("COOKIE_SECURE", "true").lower() in ("1", "true", "yes")


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


def decode_subject_token(token: str, expected_type: str) -> int:
    payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    if payload.get("type") != expected_type:
        raise JWTError("Unexpected token type")
    return int(payload["sub"])


def create_admin_token(admin_id: int) -> str:
    expire = datetime.now(timezone.utc) + timedelta(hours=ADMIN_TOKEN_EXPIRE_HOURS)
    return jwt.encode({"sub": str(admin_id), "exp": expire, "type": "admin"}, SECRET_KEY, algorithm=ALGORITHM)


def create_surgeon_session_token(device_id: int) -> str:
    expire = datetime.now(timezone.utc) + timedelta(days=SURGEON_TOKEN_EXPIRE_DAYS)
    return jwt.encode({"sub": str(device_id), "exp": expire, "type": "surgeon"}, SECRET_KEY, algorithm=ALGORITHM)
