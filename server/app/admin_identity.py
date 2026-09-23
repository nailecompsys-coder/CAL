"""Canonical portal-user identity lookup for web and native authentication."""

from __future__ import annotations

import re

from sqlalchemy import func
from sqlalchemy.orm import Session

from .models import AdminUser


PORTAL_ROLES = frozenset({"scheduler", "admin", "superadmin"})


def canonical_phone_digits(value: str | None) -> str:
    digits = re.sub(r"\D+", "", value or "")
    if len(digits) == 11 and digits.startswith("1"):
        return digits[1:]
    return digits


def find_active_portal_user(db: Session, identifier: str) -> AdminUser | None:
    """Resolve an active portal user by email or US phone number.

    A unique superadmin wins when legacy duplicate accounts share a phone number.
    Otherwise ambiguous phone matches fail closed.
    """
    submitted = (identifier or "").strip()
    if "@" in submitted:
        return db.query(AdminUser).filter(
            func.lower(AdminUser.email) == submitted.lower(),
            AdminUser.is_active == True,  # noqa: E712
            AdminUser.role.in_(PORTAL_ROLES),
        ).first()

    target = canonical_phone_digits(submitted)
    if len(target) != 10:
        return None
    candidates = db.query(AdminUser).filter(
        AdminUser.is_active == True,  # noqa: E712
        AdminUser.role.in_(PORTAL_ROLES),
        AdminUser.phone.isnot(None),
    ).all()
    matches = [row for row in candidates if canonical_phone_digits(row.phone) == target]
    if len(matches) == 1:
        return matches[0]
    superadmins = [row for row in matches if row.role == "superadmin"]
    return superadmins[0] if len(superadmins) == 1 else None
