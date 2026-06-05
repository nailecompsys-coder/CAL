"""Admin portal settings routes."""

import logging
import os
import urllib.parse

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from .. import wasabi_backup
from ..admin_settings_service import (
    add_admin_user as add_admin_user_service,
    delete_admin_user as delete_admin_user_service,
    edit_admin_user as edit_admin_user_service,
    save_rule_config,
    set_admin_password as set_admin_password_service,
    toggle_admin_user as toggle_admin_user_service,
)
from ..auth import get_current_admin, verify_password
from ..database import get_db
from ..jinja_env import templates
from ..models import AdminUser, Surgeon, SurgeonDevice
from . import admin

router = APIRouter(prefix="/admin")
log = logging.getLogger(__name__)


@router.get("/settings", response_class=HTMLResponse)
def settings_page(
    request: Request,
    db: Session = Depends(get_db),
    current_admin=Depends(get_current_admin),
):
    page_settings = admin._get_settings(db)
    admin_users = db.query(AdminUser).order_by(AdminUser.username).all()
    backups = wasabi_backup.list_backups() if wasabi_backup.is_configured() else []
    backup_ts = request.query_params.get("ts", "").strip()
    if backup_ts and request.query_params.get("msg") == "backup_ok":
        key = f"{wasabi_backup.BACKUP_PREFIX}{backup_ts}/db.sql.gz"
        new_entry = {"timestamp": backup_ts, "files": [{"name": "db.sql.gz", "key": key}], "total_bytes": 0}
        existing_ts = {backup["timestamp"] for backup in backups}
        if backup_ts not in existing_ts:
            backups = [new_entry] + backups
    registered_devices = (
        db.query(SurgeonDevice)
        .join(Surgeon)
        .order_by(Surgeon.last_name, Surgeon.first_name, SurgeonDevice.registered_at.desc())
        .all()
    )
    rule_config = {}
    all_rules = []
    try:
        from ..rules_engine.engine import get_rule_config
        from ..rules_engine.registry import ALL_RULES as _ALL_RULES

        rule_config = get_rule_config(db)
        all_rules = list(_ALL_RULES) if _ALL_RULES else []
    except Exception:
        log.exception("Failed to load rules-engine settings for admin page")
    return templates.TemplateResponse(
        "admin/settings.html",
        admin._base(
            request,
            current_admin,
            db=db,
            page_settings=page_settings,
            admin_users=admin_users,
            backups=backups,
            wasabi_configured=wasabi_backup.is_configured(),
            registered_devices=registered_devices,
            rule_config=rule_config,
            all_rules=all_rules,
        ),
    )


@router.post("/settings")
async def save_settings(
    request: Request,
    practice_name: str = Form(""),
    logo: UploadFile = File(None),
    db: Session = Depends(get_db),
    current_admin=Depends(get_current_admin),
):
    page_settings = admin._get_settings(db)
    if practice_name.strip():
        page_settings.practice_name = practice_name.strip()
    if logo and logo.filename:
        ext = os.path.splitext(logo.filename)[1].lower()
        if ext not in (".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp"):
            return RedirectResponse("/admin/settings?msg=bad_file", status_code=303)
        save_name = f"logo{ext}"
        contents = await logo.read()
        with open(os.path.join(admin.UPLOADS_DIR, save_name), "wb") as file_handle:
            file_handle.write(contents)
        page_settings.logo_filename = save_name
    db.commit()
    admin._settings_cache = page_settings
    return RedirectResponse("/admin/settings?msg=saved", status_code=303)


@router.post("/settings/rules")
async def save_rules(
    request: Request,
    db: Session = Depends(get_db),
    current_admin=Depends(get_current_admin),
):
    """Save scheduling rule config (enabled + config params) from form."""
    form = await request.form()
    save_rule_config(db, form)
    return RedirectResponse("/admin/settings?msg=rules_saved", status_code=303)


@router.post("/settings/remove-logo")
def remove_logo(
    db: Session = Depends(get_db),
    current_admin=Depends(get_current_admin),
):
    page_settings = admin._get_settings(db)
    if page_settings.logo_filename:
        path = os.path.join(admin.UPLOADS_DIR, page_settings.logo_filename)
        if os.path.exists(path):
            os.remove(path)
        page_settings.logo_filename = None
        db.commit()
        admin._settings_cache = page_settings
    return RedirectResponse("/admin/settings?msg=saved", status_code=303)


@router.post("/settings/users/add")
def add_admin_user(
    username: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
    current_admin=Depends(get_current_admin),
):
    msg = add_admin_user_service(db, username, email, password)
    return RedirectResponse(f"/admin/settings?msg={msg}", status_code=303)


@router.post("/settings/users/{user_id}/set-password")
def set_admin_password(
    user_id: int,
    new_password: str = Form(...),
    db: Session = Depends(get_db),
    current_admin=Depends(get_current_admin),
):
    msg = set_admin_password_service(db, user_id, new_password)
    return RedirectResponse(f"/admin/settings?msg={msg}", status_code=303)


@router.post("/settings/users/{user_id}/toggle")
def toggle_admin_user(
    user_id: int,
    db: Session = Depends(get_db),
    current_admin=Depends(get_current_admin),
):
    msg = toggle_admin_user_service(db, user_id)
    return RedirectResponse(f"/admin/settings?msg={msg}", status_code=303)


@router.post("/settings/users/{user_id}/edit")
def edit_admin_user(
    user_id: int,
    username: str = Form(...),
    email: str = Form(...),
    new_password: str = Form(""),
    db: Session = Depends(get_db),
    current_admin=Depends(get_current_admin),
):
    msg = edit_admin_user_service(db, user_id, username, email, new_password)
    return RedirectResponse(f"/admin/settings?msg={msg}", status_code=303)


@router.post("/settings/users/{user_id}/delete")
def delete_admin_user(
    user_id: int,
    db: Session = Depends(get_db),
    current_admin=Depends(get_current_admin),
):
    msg = delete_admin_user_service(db, user_id)
    return RedirectResponse(f"/admin/settings?msg={msg}", status_code=303)


@router.post("/settings/backup/run")
def run_backup_now(
    db: Session = Depends(get_db),
    current_admin=Depends(get_current_admin),
):
    result = wasabi_backup.run_backup()
    if result.get("success") and result.get("wasabi_ok"):
        timestamp = result.get("timestamp", "")
        url = (
            f"/admin/settings?msg=backup_ok&ts={urllib.parse.quote(timestamp)}"
            if timestamp
            else "/admin/settings?msg=backup_ok"
        )
        return RedirectResponse(url, status_code=303)
    if result.get("success") and not result.get("wasabi_ok"):
        return RedirectResponse("/admin/settings?msg=backup_upload_failed", status_code=303)
    err = result.get("error", "Backup failed")
    return RedirectResponse(
        "/admin/settings?msg=backup_failed&err=" + urllib.parse.quote(err[:200]),
        status_code=303,
    )


@router.post("/settings/backup/restore")
def restore_backup(
    wasabi_key: str = Form(...),
    password: str = Form(...),
    confirm: str = Form(...),
    db: Session = Depends(get_db),
    current_admin=Depends(get_current_admin),
):
    if not verify_password(password, current_admin.password_hash):
        return RedirectResponse("/admin/settings?msg=restore_bad_password", status_code=303)
    result = wasabi_backup.restore_backup(wasabi_key, password, confirm.strip())
    if result.get("success"):
        return RedirectResponse("/admin/settings?msg=restore_ok", status_code=303)
    err = result.get("error", "Restore failed")
    return RedirectResponse(
        "/admin/settings?msg=restore_failed&err=" + urllib.parse.quote(err[:200]),
        status_code=303,
    )
