"""Admin portal settings hub and system pages."""

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
    recent_admin_notifications,
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
    unread_admin_notification_count,
)
from ..auth import get_current_admin, verify_password
from ..database import get_db
from ..jinja_env import templates
from ..models import AdminUser, Surgeon
from ..surgeon_visibility import visible_surgeons
from . import admin
from .admin import _sort_surgeons_physicians_first

router = APIRouter(prefix="/admin")
log = logging.getLogger(__name__)


def _settings_base(request, current_admin, db, **extra):
    return admin._base(request, current_admin, db=db, settings_hub=True, **extra)


@router.get("/settings", response_class=HTMLResponse)
def settings_root(
    request: Request,
    db: Session = Depends(get_db),
    current_admin=Depends(get_current_admin),
):
    return RedirectResponse("/admin/settings/practice", status_code=303)


@router.get("/settings/practice", response_class=HTMLResponse)
@router.get("/branding", response_class=HTMLResponse)
def practice_page(
    request: Request,
    db: Session = Depends(get_db),
    current_admin=Depends(get_current_admin),
):
    return templates.TemplateResponse(
        "admin/settings_practice.html",
        _settings_base(
            request,
            current_admin,
            db,
            page_settings=admin._get_settings(db),
        ),
    )


@router.get("/settings/people", response_class=HTMLResponse)
def people_page(
    request: Request,
    db: Session = Depends(get_db),
    current_admin=Depends(get_current_admin),
):
    surgeons = _sort_surgeons_physicians_first(visible_surgeons(db.query(Surgeon).order_by(Surgeon.last_name).all()))
    admin_users = db.query(AdminUser).order_by(AdminUser.username).all()
    return templates.TemplateResponse(
        "admin/settings_people.html",
        _settings_base(request, current_admin, db, surgeons=surgeons, admin_users=admin_users),
    )


@router.get("/users", response_class=HTMLResponse)
def users_redirect():
    return RedirectResponse("/admin/settings/people?filter=portal", status_code=303)


@router.get("/settings/locations", response_class=HTMLResponse)
def settings_locations_redirect():
    return RedirectResponse("/admin/locations", status_code=303)


@router.get("/settings/clinic-groups", response_class=HTMLResponse)
def settings_clinic_groups_redirect():
    return RedirectResponse("/admin/clinic-groups", status_code=303)


@router.get("/settings/scheduling-rules", response_class=HTMLResponse)
@router.get("/scheduling-rules", response_class=HTMLResponse)
def scheduling_rules_page(
    request: Request,
    db: Session = Depends(get_db),
    current_admin=Depends(get_current_admin),
):
    rule_config = {}
    all_rules = []
    try:
        rule_config, all_rules = rules_engine_settings(db)
    except Exception:
        log.exception("Failed to load rules-engine settings")
    return templates.TemplateResponse(
        "admin/scheduling_rules.html",
        _settings_base(request, current_admin, db, rule_config=rule_config, all_rules=all_rules),
    )


@router.get("/settings/access", response_class=HTMLResponse)
def access_page(
    request: Request,
    db: Session = Depends(get_db),
    current_admin=Depends(get_current_admin),
):
    return templates.TemplateResponse(
        "admin/settings_access.html",
        _settings_base(
            request,
            current_admin,
            db,
            registered_devices=registered_surgeon_devices(db),
            otp_audit_logs=recent_otp_audit_logs(db, limit=100),
        ),
    )


@router.get("/mobile-devices", response_class=HTMLResponse)
@router.get("/otp-sign-in", response_class=HTMLResponse)
def access_legacy_redirect():
    return RedirectResponse("/admin/settings/access", status_code=303)


@router.get("/settings/notifications", response_class=HTMLResponse)
@router.get("/notifications", response_class=HTMLResponse)
def notifications_page(
    request: Request,
    db: Session = Depends(get_db),
    current_admin=Depends(get_current_admin),
):
    return templates.TemplateResponse(
        "admin/notifications.html",
        _settings_base(
            request,
            current_admin,
            db,
            admin_notifications=recent_admin_notifications(db, current_admin.id),
            admin_unread_notifications=unread_admin_notification_count(db, current_admin.id),
        ),
    )


@router.get("/settings/backup", response_class=HTMLResponse)
@router.get("/backup", response_class=HTMLResponse)
def backup_page(
    request: Request,
    db: Session = Depends(get_db),
    current_admin=Depends(get_current_admin),
):
    return templates.TemplateResponse(
        "admin/backup.html",
        _settings_base(
            request,
            current_admin,
            db,
            backups=settings_backups(request),
            backup_job=backup_status(),
            wasabi_configured=wasabi_backup.is_configured(),
        ),
    )


@router.post("/settings/practice")
@router.post("/branding")
@router.post("/settings")
async def save_practice(
    request: Request,
    practice_name: str = Form(""),
    practice_address: str = Form(""),
    practice_city: str = Form(""),
    practice_state: str = Form(""),
    practice_zip: str = Form(""),
    practice_phone: str = Form(""),
    practice_email: str = Form(""),
    show_or_patient_procedure_form: str = Form(""),
    logo: UploadFile = File(None),
    db: Session = Depends(get_db),
    current_admin=Depends(get_current_admin),
):
    page_settings = admin._get_settings(db)
    msg = await save_practice_settings(
        db,
        page_settings,
        practice_name,
        logo,
        admin.UPLOADS_DIR,
        show_or_patient_procedure_form == "1",
        practice_address=practice_address,
        practice_city=practice_city,
        practice_state=practice_state,
        practice_zip=practice_zip,
        practice_phone=practice_phone,
        practice_email=practice_email,
    )
    admin._settings_cache = page_settings
    return RedirectResponse(f"/admin/settings/practice?msg={msg}", status_code=303)


@router.post("/settings/scheduling-rules")
@router.post("/scheduling-rules")
@router.post("/settings/rules")
async def save_rules(
    request: Request,
    db: Session = Depends(get_db),
    current_admin=Depends(get_current_admin),
):
    form = await request.form()
    save_rule_config(db, form)
    return RedirectResponse("/admin/settings/scheduling-rules?msg=rules_saved", status_code=303)


@router.post("/settings/practice/remove-logo")
@router.post("/branding/remove-logo")
@router.post("/settings/remove-logo")
def remove_logo(
    db: Session = Depends(get_db),
    current_admin=Depends(get_current_admin),
):
    page_settings = admin._get_settings(db)
    remove_practice_logo(db, page_settings, admin.UPLOADS_DIR)
    admin._settings_cache = page_settings
    return RedirectResponse("/admin/settings/practice?msg=saved", status_code=303)


@router.post("/users/add")
@router.post("/settings/users/add")
@router.post("/settings/people/users/add")
def add_admin_user(
    username: str = Form(...),
    first_name: str = Form(""),
    last_name: str = Form(""),
    email: str = Form(...),
    phone: str = Form(""),
    password: str = Form(...),
    role: str = Form("admin"),
    notify_day_off_requests: str = Form(""),
    notify_schedule_changes: str = Form(""),
    sms_fallback_enabled: str = Form(""),
    db: Session = Depends(get_db),
    current_admin=Depends(get_current_admin),
):
    msg = add_admin_user_service(
        db,
        username,
        email,
        password,
        role,
        first_name,
        last_name,
        phone,
        notify_day_off_requests == "1",
        notify_schedule_changes == "1",
        sms_fallback_enabled == "1",
    )
    return RedirectResponse(f"/admin/settings/people?filter=portal&msg={msg}", status_code=303)


@router.post("/users/{user_id}/set-password")
@router.post("/settings/users/{user_id}/set-password")
@router.post("/settings/people/users/{user_id}/set-password")
def set_admin_password(
    user_id: int,
    new_password: str = Form(...),
    db: Session = Depends(get_db),
    current_admin=Depends(get_current_admin),
):
    msg = set_admin_password_service(db, user_id, new_password)
    return RedirectResponse(f"/admin/settings/people?filter=portal&msg={msg}", status_code=303)


@router.post("/users/{user_id}/toggle")
@router.post("/settings/users/{user_id}/toggle")
@router.post("/settings/people/users/{user_id}/toggle")
def toggle_admin_user(
    user_id: int,
    db: Session = Depends(get_db),
    current_admin=Depends(get_current_admin),
):
    msg = toggle_admin_user_service(db, user_id)
    return RedirectResponse(f"/admin/settings/people?filter=portal&msg={msg}", status_code=303)


@router.post("/users/{user_id}/edit")
@router.post("/settings/users/{user_id}/edit")
@router.post("/settings/people/users/{user_id}/edit")
def edit_admin_user(
    user_id: int,
    username: str = Form(...),
    first_name: str = Form(""),
    last_name: str = Form(""),
    email: str = Form(...),
    phone: str = Form(""),
    new_password: str = Form(""),
    role: str = Form("admin"),
    notify_day_off_requests: str = Form(""),
    notify_schedule_changes: str = Form(""),
    sms_fallback_enabled: str = Form(""),
    db: Session = Depends(get_db),
    current_admin=Depends(get_current_admin),
):
    msg = edit_admin_user_service(
        db,
        user_id,
        username,
        email,
        new_password,
        role,
        first_name,
        last_name,
        phone,
        notify_day_off_requests == "1",
        notify_schedule_changes == "1",
        sms_fallback_enabled == "1",
    )
    return RedirectResponse(f"/admin/settings/people?filter=portal&msg={msg}", status_code=303)


@router.post("/users/{user_id}/delete")
@router.post("/settings/users/{user_id}/delete")
@router.post("/settings/people/users/{user_id}/delete")
def delete_admin_user(
    user_id: int,
    db: Session = Depends(get_db),
    current_admin=Depends(get_current_admin),
):
    msg = delete_admin_user_service(db, user_id)
    return RedirectResponse(f"/admin/settings/people?filter=portal&msg={msg}", status_code=303)


@router.post("/settings/backup/run")
@router.post("/backup/run")
def run_backup_now(
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_admin=Depends(get_current_admin),
):
    if not start_backup_job(current_admin.username):
        return RedirectResponse("/admin/settings/backup?msg=backup_running", status_code=303)
    background_tasks.add_task(run_backup_job, current_admin.username)
    return RedirectResponse("/admin/settings/backup?msg=backup_started", status_code=303)


@router.post("/settings/backup/restore")
@router.post("/backup/restore")
def restore_backup(
    wasabi_key: str = Form(...),
    password: str = Form(...),
    confirm: str = Form(...),
    db: Session = Depends(get_db),
    current_admin=Depends(get_current_admin),
):
    if not verify_password(password, current_admin.password_hash):
        return RedirectResponse("/admin/settings/backup?msg=restore_bad_password", status_code=303)
    result = wasabi_backup.restore_backup(wasabi_key, password, confirm.strip())
    return RedirectResponse(restore_result_url(result), status_code=303)
