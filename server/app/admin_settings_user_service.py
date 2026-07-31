from __future__ import annotations

import json
import re
import secrets

from sqlalchemy.orm import Session

from .auth import hash_password
from .admin_surgeon_service import format_us_phone
from .models import AdminUser, SchedulingRuleConfig
from .rules_engine.registry import ALL_RULES


def save_rule_config(db: Session, form) -> None:
    for rule in ALL_RULES:
        row = db.query(SchedulingRuleConfig).filter(SchedulingRuleConfig.rule_id == rule.rule_id).first()
        if not row:
            row = SchedulingRuleConfig(rule_id=rule.rule_id, enabled=True, config="{}")
            db.add(row)
        enabled_key = f"rule_{rule.rule_id}_enabled"
        row.enabled = form.get(enabled_key) == "1"
        config = dict(rule.default_config) if rule.default_config else {}
        for schema_item in rule.config_schema:
            key = schema_item.get("key")
            if not key:
                continue
            form_key = f"rule_{rule.rule_id}_{key}"
            val = form.get(form_key, "").strip()
            if schema_item.get("type") == "number":
                if val != "":
                    try:
                        config[key] = int(val)
                    except ValueError:
                        config[key] = config.get(key, 0)
            elif val:
                config[key] = val
        row.config = json.dumps(config)
    db.commit()


_ALLOWED_PORTAL_ROLES = frozenset({"admin", "scheduler", "superadmin"})


def _normalize_role(role: str) -> str:
    value = (role or "").strip().lower()
    if value in _ALLOWED_PORTAL_ROLES:
        return value
    return "admin"


def _username_base_from_identity(
    email: str,
    first_name: str = "",
    last_name: str = "",
    phone: str = "",
) -> str:
    """Derive a unique-friendly username for DB uniqueness; OTP uses email/phone."""
    if email and "@" in email:
        local = email.split("@", 1)[0].lower()
        local = re.sub(r"[^a-z0-9._-]", "", local)
        if local:
            return local[:64]
    name = f"{(first_name or '').strip()}.{(last_name or '').strip()}".strip(".").lower()
    name = re.sub(r"[^a-z0-9._-]", "", name)
    if name:
        return name[:64]
    digits = re.sub(r"\D+", "", phone or "")
    if digits:
        return f"user{digits[-10:]}"[:64]
    return "user"


def _unique_username(db: Session, base: str) -> str:
    candidate = (base or "user")[:64]
    n = 2
    while db.query(AdminUser).filter(AdminUser.username == candidate).first():
        suffix = str(n)
        candidate = f"{(base or 'user')[: max(1, 64 - len(suffix))]}{suffix}"
        n += 1
    return candidate


def add_admin_user(
    db: Session,
    username: str,
    email: str,
    password: str = "",
    role: str = "admin",
    first_name: str = "",
    last_name: str = "",
    phone: str = "",
    notify_day_off_requests: bool = True,
    notify_schedule_changes: bool = True,
    sms_fallback_enabled: bool = False,
) -> str:
    email = (email or "").strip().lower()
    phone_fmt = format_us_phone(phone)
    if not email and not (phone_fmt or "").strip():
        return "user_invalid"
    if not email:
        # AdminUser.email is required; OTP portal login keys off email.
        # Phone-only portal users are not supported yet.
        return "user_invalid"
    username = (username or "").strip().lower()
    if not username:
        username = _unique_username(
            db,
            _username_base_from_identity(email, first_name, last_name, phone_fmt),
        )
    else:
        if db.query(AdminUser).filter(AdminUser.username == username).first():
            return "username_taken"
    password = (password or "").strip()
    if password and len(password) < 8:
        return "password_short"
    if not password:
        # OTP is the primary sign-in; keep a random hash for legacy password column.
        password = secrets.token_urlsafe(24)
    if db.query(AdminUser).filter(AdminUser.email == email).first():
        return "email_taken"
    db.add(
        AdminUser(
            username=username,
            first_name=first_name.strip() or None,
            last_name=last_name.strip() or None,
            email=email,
            phone=phone_fmt,
            password_hash=hash_password(password),
            role=_normalize_role(role),
            notify_day_off_requests=notify_day_off_requests,
            notify_schedule_changes=notify_schedule_changes,
            sms_fallback_enabled=sms_fallback_enabled,
            is_active=True,
        )
    )
    db.commit()
    return "user_added"


def set_admin_password(db: Session, user_id: int, new_password: str) -> str:
    user = db.get(AdminUser, user_id)
    if not user:
        return "user_not_found"
    if len(new_password) < 8:
        return "password_short"
    user.password_hash = hash_password(new_password)
    db.commit()
    return "password_updated"


def toggle_admin_user(db: Session, user_id: int) -> str:
    user = db.get(AdminUser, user_id)
    if not user:
        return "user_not_found"
    active_count = db.query(AdminUser).filter(AdminUser.is_active == True).count()
    if user.is_active and active_count <= 1:
        return "last_admin"
    user.is_active = not user.is_active
    db.commit()
    return "user_updated"


def edit_admin_user(
    db: Session,
    user_id: int,
    username: str,
    email: str,
    new_password: str,
    role: str = "admin",
    first_name: str = "",
    last_name: str = "",
    phone: str = "",
    notify_day_off_requests: bool = True,
    notify_schedule_changes: bool = True,
    sms_fallback_enabled: bool = False,
) -> str:
    user = db.get(AdminUser, user_id)
    if not user:
        return "user_not_found"
    email = (email or "").strip().lower()
    if not email:
        return "user_invalid"
    username = (username or "").strip().lower()
    if not username:
        # OTP-first edits keep the existing internal username.
        username = user.username
    other_username = db.query(AdminUser).filter(AdminUser.username == username, AdminUser.id != user_id).first()
    if other_username:
        return "username_taken"
    other_email = db.query(AdminUser).filter(AdminUser.email == email, AdminUser.id != user_id).first()
    if other_email:
        return "email_taken"
    user.username = username
    user.first_name = first_name.strip() or None
    user.last_name = last_name.strip() or None
    user.email = email
    user.phone = format_us_phone(phone)
    user.role = _normalize_role(role)
    user.notify_day_off_requests = notify_day_off_requests
    user.notify_schedule_changes = notify_schedule_changes
    user.sms_fallback_enabled = sms_fallback_enabled
    if new_password and len(new_password.strip()) >= 8:
        user.password_hash = hash_password(new_password.strip())
    db.commit()
    return "user_edited"


def delete_admin_user(db: Session, user_id: int) -> str:
    user = db.get(AdminUser, user_id)
    if not user:
        return "user_not_found"
    active_count = db.query(AdminUser).filter(AdminUser.is_active == True).count()
    if user.is_active and active_count <= 1:
        return "last_admin"
    db.delete(user)
    db.commit()
    return "user_deleted"
