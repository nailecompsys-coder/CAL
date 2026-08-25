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
from ..admin_notification_ack import ack_informational_notification
from ..admin_surgeon_service import (
    add_surgeon as add_surgeon_service,
    surgeon_fields,
    update_surgeon as update_surgeon_service,
)
from ..auth import get_current_admin, verify_password
from ..database import get_db
from ..jinja_env import templates
from ..models import AdminUser, Surgeon
from ..surgeon_visibility import visible_surgeons
from . import admin
from .admin import _next_physician_sort_order, _sort_surgeons_physicians_first

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


def _users_filter_for_portal(role: str | None) -> str:
    """Map admin_users.role → Users section filter (scheduler→schedulers, else staff/Admins)."""
    return "schedulers" if (role or "").strip().lower() == "scheduler" else "staff"


def _users_portal_redirect(role: str | None, msg: str | None = None) -> RedirectResponse:
    filt = _users_filter_for_portal(role)
    url = f"/admin/settings/people?filter={filt}"
    if msg:
        url = f"{url}&msg={msg}"
    return RedirectResponse(url, status_code=303)


@router.get("/users", response_class=HTMLResponse)
def users_redirect():
    return RedirectResponse("/admin/settings/people?filter=staff", status_code=303)


@router.get("/settings/locations", response_class=HTMLResponse)
def settings_locations_redirect():
    return RedirectResponse("/admin/locations", status_code=303)


@router.get("/settings/clinic-groups", response_class=HTMLResponse)
def settings_clinic_groups_redirect():
    return RedirectResponse("/admin/clinic-groups", status_code=303)


@router.get("/settings/co-surgeon-pairs", response_class=HTMLResponse)
def settings_co_surgeon_pairs_redirect():
    return RedirectResponse("/admin/co-surgeon-pairs", status_code=303)


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


@router.get("/notifications/{notification_id}/ack")
def ack_notification(
    notification_id: int,
    db: Session = Depends(get_db),
    current_admin=Depends(get_current_admin),
):
    href = ack_informational_notification(db, current_admin.id, notification_id)
    return RedirectResponse(href or "/admin/dashboard", status_code=303)


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


@router.post("/settings/people/add")
def add_people_user(
    position: str = Form(...),
    first_name: str = Form(...),
    last_name: str = Form(...),
    email: str = Form(""),
    phone: str = Form(""),
    suffix: str = Form(""),
    sort_order: int = Form(0),
    access_level: str = Form("admin"),
    notify_day_off_requests: str = Form(""),
    notify_schedule_changes: str = Form(""),
    sms_fallback_enabled: str = Form(""),
    db: Session = Depends(get_db),
    current_admin=Depends(get_current_admin),
):
    """Unified Add user — position inside the form; OTP via email and/or phone."""
    pos = (position or "").strip().lower()
    email_clean = (email or "").strip()
    phone_clean = (phone or "").strip()

    if pos in {"surgeon", "pa"}:
        if not email_clean and not phone_clean:
            return RedirectResponse("/admin/settings/people?msg=otp_contact_required", status_code=303)
        staff_type = "staff" if pos == "pa" else "physician"
        fields = surgeon_fields(
            first_name,
            last_name,
            suffix,
            staff_type,
            email_clean,
            phone_clean,
            sort_order,
            lambda: _next_physician_sort_order(db),
        )
        add_surgeon_service(db, fields)
        filt = "pas" if staff_type == "staff" else "surgeons"
        return RedirectResponse(f"/admin/settings/people?filter={filt}&msg=added", status_code=303)

    if pos in {"scheduler", "staff"}:
        if not email_clean:
            return RedirectResponse("/admin/settings/people?msg=otp_contact_required", status_code=303)
        if pos == "scheduler":
            role = "scheduler"
        else:
            level = (access_level or "admin").strip().lower()
            role = "superadmin" if level == "superadmin" else "admin"
        msg = add_admin_user_service(
            db,
            "",  # username auto-derived; OTP uses email/phone
            email_clean,
            "",  # password auto-generated; not used for OTP sign-in
            role,
            first_name,
            last_name,
            phone_clean,
            notify_day_off_requests == "1",
            notify_schedule_changes == "1",
            sms_fallback_enabled == "1",
        )
        return _users_portal_redirect(role, msg)

    return RedirectResponse("/admin/settings/people?msg=invalid_position", status_code=303)


@router.post("/users/add")
@router.post("/settings/users/add")
@router.post("/settings/people/users/add")
def add_admin_user(
    username: str = Form(""),
    first_name: str = Form(""),
    last_name: str = Form(""),
    email: str = Form(""),
    phone: str = Form(""),
    password: str = Form(""),
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
    return _users_portal_redirect(role, msg)


@router.post("/users/{user_id}/set-password")
@router.post("/settings/users/{user_id}/set-password")
@router.post("/settings/people/users/{user_id}/set-password")
def set_admin_password(
    user_id: int,
    new_password: str = Form(...),
    db: Session = Depends(get_db),
    current_admin=Depends(get_current_admin),
):
    user = db.get(AdminUser, user_id)
    msg = set_admin_password_service(db, user_id, new_password)
    return _users_portal_redirect(user.role if user else "admin", msg)


@router.post("/users/{user_id}/toggle")
@router.post("/settings/users/{user_id}/toggle")
@router.post("/settings/people/users/{user_id}/toggle")
def toggle_admin_user(
    user_id: int,
    db: Session = Depends(get_db),
    current_admin=Depends(get_current_admin),
):
    user = db.get(AdminUser, user_id)
    role = user.role if user else "admin"
    msg = toggle_admin_user_service(db, user_id)
    return _users_portal_redirect(role, msg)


@router.post("/users/{user_id}/edit")
@router.post("/settings/users/{user_id}/edit")
@router.post("/settings/people/users/{user_id}/edit")
def edit_admin_user(
    user_id: int,
    username: str = Form(""),
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
    """Legacy portal-only edit (kept for /admin/users). Prefer /settings/people/edit."""
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
    return _users_portal_redirect(role, msg)


@router.post("/settings/people/edit")
def edit_people_user(
    user_kind: str = Form(...),
    user_id: int = Form(...),
    position: str = Form(...),
    first_name: str = Form(...),
    last_name: str = Form(...),
    email: str = Form(""),
    phone: str = Form(""),
    suffix: str = Form(""),
    sort_order: int = Form(0),
    access_level: str = Form("admin"),
    notify_day_off_requests: str = Form(""),
    notify_schedule_changes: str = Form(""),
    sms_fallback_enabled: str = Form(""),
    db: Session = Depends(get_db),
    current_admin=Depends(get_current_admin),
):
    """Unified Edit user — same shape as Add; OTP via email and/or phone."""
    kind = (user_kind or "").strip().lower()
    pos = (position or "").strip().lower()
    email_clean = (email or "").strip()
    phone_clean = (phone or "").strip()
    clinical_target = pos in {"surgeon", "pa"}
    portal_target = pos in {"scheduler", "staff"}

    if kind not in {"clinical", "portal"} or not (clinical_target or portal_target):
        return RedirectResponse("/admin/settings/people?msg=invalid_position", status_code=303)

    if clinical_target and not email_clean and not phone_clean:
        return RedirectResponse("/admin/settings/people?msg=otp_contact_required", status_code=303)
    if portal_target and not email_clean:
        return RedirectResponse("/admin/settings/people?msg=otp_contact_required", status_code=303)

    def _portal_role() -> str:
        if pos == "scheduler":
            return "scheduler"
        level = (access_level or "admin").strip().lower()
        return "superadmin" if level == "superadmin" else "admin"

    def _clinical_staff_type() -> str:
        return "staff" if pos == "pa" else "physician"

    notify_day = notify_day_off_requests == "1"
    notify_sched = notify_schedule_changes == "1"
    sms_fb = sms_fallback_enabled == "1"

    # Same-table updates
    if kind == "clinical" and clinical_target:
        row = db.get(Surgeon, user_id)
        if not row:
            return RedirectResponse("/admin/settings/people?msg=user_not_found", status_code=303)
        staff_type = _clinical_staff_type()
        fields = surgeon_fields(
            first_name,
            last_name,
            suffix,
            staff_type,
            email_clean,
            phone_clean,
            sort_order,
            lambda: _next_physician_sort_order(db),
        )
        update_surgeon_service(db, user_id, fields)
        filt = "pas" if staff_type == "staff" else "surgeons"
        return RedirectResponse(f"/admin/settings/people?filter={filt}&msg=updated", status_code=303)

    if kind == "portal" and portal_target:
        role = _portal_role()
        msg = edit_admin_user_service(
            db,
            user_id,
            "",  # keep existing username
            email_clean,
            "",  # password unchanged; use Password action if needed
            role,
            first_name,
            last_name,
            phone_clean,
            notify_day,
            notify_sched,
            sms_fb,
        )
        return _users_portal_redirect(role, msg if msg != "user_edited" else "updated")

    # Cross-type: deactivate old row, create new in the other table (preserves FKs).
    if kind == "clinical" and portal_target:
        row = db.get(Surgeon, user_id)
        if not row:
            return RedirectResponse("/admin/settings/people?msg=user_not_found", status_code=303)
        role = _portal_role()
        msg = add_admin_user_service(
            db,
            "",
            email_clean,
            "",
            role,
            first_name,
            last_name,
            phone_clean,
            notify_day,
            notify_sched,
            sms_fb,
        )
        if msg != "user_added":
            return _users_portal_redirect(role, msg)
        if row.is_active:
            row.is_active = False
            db.commit()
        return _users_portal_redirect(role, "position_cross_type")

    if kind == "portal" and clinical_target:
        row = db.get(AdminUser, user_id)
        if not row:
            return RedirectResponse("/admin/settings/people?msg=user_not_found", status_code=303)
        if row.is_active:
            active_count = db.query(AdminUser).filter(AdminUser.is_active == True).count()  # noqa: E712
            if active_count <= 1:
                return RedirectResponse("/admin/settings/people?msg=last_admin", status_code=303)
        staff_type = _clinical_staff_type()
        fields = surgeon_fields(
            first_name,
            last_name,
            suffix,
            staff_type,
            email_clean,
            phone_clean,
            sort_order,
            lambda: _next_physician_sort_order(db),
        )
        add_surgeon_service(db, fields)
        if row.is_active:
            row.is_active = False
            db.commit()
        filt = "pas" if staff_type == "staff" else "surgeons"
        return RedirectResponse(
            f"/admin/settings/people?filter={filt}&msg=position_cross_type",
            status_code=303,
        )

    return RedirectResponse("/admin/settings/people?msg=invalid_position", status_code=303)


@router.post("/users/{user_id}/delete")
@router.post("/settings/users/{user_id}/delete")
@router.post("/settings/people/users/{user_id}/delete")
def delete_admin_user(
    user_id: int,
    db: Session = Depends(get_db),
    current_admin=Depends(get_current_admin),
):
    user = db.get(AdminUser, user_id)
    role = user.role if user else "admin"
    msg = delete_admin_user_service(db, user_id)
    return _users_portal_redirect(role, msg)


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
