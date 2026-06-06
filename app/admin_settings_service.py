"""Business logic for admin settings routes."""

import json
import os
import urllib.parse

from sqlalchemy.orm import Session

from . import wasabi_backup
from .auth import hash_password
from .models import AdminUser, SchedulingRuleConfig, Surgeon, SurgeonDevice
from .rules_engine.registry import ALL_RULES


def settings_backups(request) -> list[dict]:
    backups = wasabi_backup.list_backups() if wasabi_backup.is_configured() else []
    backup_ts = request.query_params.get("ts", "").strip()
    if backup_ts and request.query_params.get("msg") == "backup_ok":
        key = f"{wasabi_backup.BACKUP_PREFIX}{backup_ts}/db.sql.gz"
        new_entry = {"timestamp": backup_ts, "files": [{"name": "db.sql.gz", "key": key}], "total_bytes": 0}
        existing_ts = {backup["timestamp"] for backup in backups}
        if backup_ts not in existing_ts:
            backups = [new_entry] + backups
    return backups


def registered_surgeon_devices(db: Session) -> list[SurgeonDevice]:
    return (
        db.query(SurgeonDevice)
        .join(Surgeon)
        .order_by(Surgeon.last_name, Surgeon.first_name, SurgeonDevice.registered_at.desc())
        .all()
    )


def rules_engine_settings(db: Session) -> tuple[dict, list]:
    from .rules_engine.engine import get_rule_config
    from .rules_engine.registry import ALL_RULES as _ALL_RULES

    return get_rule_config(db), list(_ALL_RULES) if _ALL_RULES else []


async def save_practice_settings(db: Session, page_settings, practice_name: str, logo, uploads_dir: str) -> str:
    if practice_name.strip():
        page_settings.practice_name = practice_name.strip()
    if logo and logo.filename:
        ext = os.path.splitext(logo.filename)[1].lower()
        if ext not in (".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp"):
            return "bad_file"
        save_name = f"logo{ext}"
        contents = await logo.read()
        with open(os.path.join(uploads_dir, save_name), "wb") as file_handle:
            file_handle.write(contents)
        page_settings.logo_filename = save_name
    db.commit()
    return "saved"


def remove_practice_logo(db: Session, page_settings, uploads_dir: str) -> None:
    if page_settings.logo_filename:
        path = os.path.join(uploads_dir, page_settings.logo_filename)
        if os.path.exists(path):
            os.remove(path)
        page_settings.logo_filename = None
        db.commit()


def backup_result_url(result: dict) -> str:
    if result.get("success") and result.get("wasabi_ok"):
        timestamp = result.get("timestamp", "")
        return (
            f"/admin/settings?msg=backup_ok&ts={urllib.parse.quote(timestamp)}"
            if timestamp
            else "/admin/settings?msg=backup_ok"
        )
    if result.get("success") and not result.get("wasabi_ok"):
        return "/admin/settings?msg=backup_upload_failed"
    err = result.get("error", "Backup failed")
    return "/admin/settings?msg=backup_failed&err=" + urllib.parse.quote(err[:200])


def restore_result_url(result: dict) -> str:
    if result.get("success"):
        return "/admin/settings?msg=restore_ok"
    err = result.get("error", "Restore failed")
    return "/admin/settings?msg=restore_failed&err=" + urllib.parse.quote(err[:200])


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


def add_admin_user(db: Session, username: str, email: str, password: str) -> str:
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
            role="admin",
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


def edit_admin_user(db: Session, user_id: int, username: str, email: str, new_password: str) -> str:
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
