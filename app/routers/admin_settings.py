"""Admin portal settings routes."""

import logging

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from .. import wasabi_backup
from ..backup_jobs import backup_status, run_backup_job, start_backup_job
from ..admin_settings_service import (
    add_admin_user as add_admin_user_service,
    delete_admin_user as delete_admin_user_service,
    edit_admin_user as edit_admin_user_service,
    recent_otp_audit_logs,
    registered_surgeon_devices,
    remove_practice_logo,
    restore_result_url,
    rules_engine_settings,
    save_rule_config,
    save_practice_settings,
    set_admin_password as set_admin_password_service,
    settings_backups,
    toggle_admin_user as toggle_admin_user_service,
)
from ..auth import get_current_admin, verify_password
from ..database import get_db
from ..jinja_env import templates
from ..models import AdminUser
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
    backups = settings_backups(request)
    backup_job = backup_status()
    registered_devices = registered_surgeon_devices(db)
    otp_audit_logs = recent_otp_audit_logs(db)
    rule_config = {}
    all_rules = []
    try:
        rule_config, all_rules = rules_engine_settings(db)
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
            backup_job=backup_job,
            wasabi_configured=wasabi_backup.is_configured(),
            registered_devices=registered_devices,
            otp_audit_logs=otp_audit_logs,
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
    msg = await save_practice_settings(db, page_settings, practice_name, logo, admin.UPLOADS_DIR)
    admin._settings_cache = page_settings
    return RedirectResponse(f"/admin/settings?msg={msg}", status_code=303)


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
    remove_practice_logo(db, page_settings, admin.UPLOADS_DIR)
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
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_admin=Depends(get_current_admin),
):
    if not start_backup_job(current_admin.username):
        return RedirectResponse("/admin/settings?msg=backup_running", status_code=303)
    background_tasks.add_task(run_backup_job, current_admin.username)
    return RedirectResponse("/admin/settings?msg=backup_started", status_code=303)


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
    return RedirectResponse(restore_result_url(result), status_code=303)
