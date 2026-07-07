from __future__ import annotations

import json

from sqlalchemy.orm import Session

from .auth import hash_password
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


def _normalize_role(role: str) -> str:
    return "scheduler" if role == "scheduler" else "admin"


def add_admin_user(db: Session, username: str, email: str, password: str, role: str = "admin") -> str:
    username = username.strip().lower()
    email = email.strip().lower()
    if not username or not email:
        return "user_invalid"
    if len(password) < 8:
        return "password_short"
    if db.query(AdminUser).filter(AdminUser.username == username).first():
        return "username_taken"
    if db.query(AdminUser).filter(AdminUser.email == email).first():
        return "email_taken"
    db.add(
        AdminUser(
            username=username,
            email=email,
            password_hash=hash_password(password),
            role=_normalize_role(role),
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


def edit_admin_user(db: Session, user_id: int, username: str, email: str, new_password: str, role: str = "admin") -> str:
    user = db.get(AdminUser, user_id)
    if not user:
        return "user_not_found"
    username = username.strip().lower()
    email = email.strip().lower()
    if not username or not email:
        return "user_invalid"
    other_username = db.query(AdminUser).filter(AdminUser.username == username, AdminUser.id != user_id).first()
    if other_username:
        return "username_taken"
    other_email = db.query(AdminUser).filter(AdminUser.email == email, AdminUser.id != user_id).first()
    if other_email:
        return "email_taken"
    user.username = username
    user.email = email
    user.role = _normalize_role(role)
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
