"""Admin portal HTML routes."""
import os
import urllib.parse
from datetime import date, timedelta

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import case, func
from sqlalchemy.orm import Session

from ..admin_dashboard_stats_service import dashboard_today_volume_stats
from ..aprima_cache_service import main_office_patients_by_weekday, sync_status_payload
from ..auth import (
    get_current_admin,
)
from ..database import get_db
from ..jinja_env import templates
from ..models import (
    AdminUser, CallRotation, DayOff, Meeting, SiteSettings, Surgeon,
)
from ..native_home_serializers import is_clinic_day_meeting
from ..paths import UPLOADS_DIR
from ..surgeon_visibility import surgeon_is_visible
from .. import wasabi_backup
from .. import __version__ as app_version

os.makedirs(UPLOADS_DIR, exist_ok=True)


def _warn_redirect(base_url: str, conflicts: list[str]) -> RedirectResponse:
    """Redirect with a ?warn= param if there are conflicts."""
    if conflicts:
        warn = urllib.parse.quote(" · ".join(conflicts[:6]))
        sep = "&" if "?" in base_url else "?"
        return RedirectResponse(f"{base_url}{sep}warn={warn}", status_code=303)
    return RedirectResponse(base_url, status_code=303)

router = APIRouter(prefix="/admin")


_settings_cache: SiteSettings | None = None


def _surgeon_sort_key(s):
    is_physician = (getattr(s, "staff_type", None) or "physician") == "physician"
    rank = getattr(s, "sort_order", 0) or 0
    return (
        0 if is_physician else 1,
        rank if is_physician and rank > 0 else 999999,
        (s.last_name or "").lower(),
        (s.first_name or "").lower(),
        getattr(s, "id", 0),
    )


def _get_settings(db: Session) -> SiteSettings:
    """Return site settings for the current request. Always load from current session so the instance is attached (avoids DetachedInstanceError in templates)."""
    global _settings_cache
    s = db.get(SiteSettings, 1)
    if not s:
        s = SiteSettings(id=1, practice_name="Mid Florida Surgical")
        db.add(s)
        db.commit()
    _settings_cache = s
    return s


def _base(request: Request, admin: AdminUser, db: Session | None = None, **kwargs):
    """Build base template context. Pass db= so settings is loaded in current session (avoids DetachedInstanceError)."""
    settings = _get_settings(db) if db is not None else _settings_cache
    return {
        "request": request,
        "admin": admin,
        "today": date.today(),
        "settings": settings,
        "app_version": app_version,
        "wasabi_configured": wasabi_backup.is_configured(),
        **kwargs,
    }


def _sort_surgeons_physicians_first(surgeons: list) -> list:
    """Physicians first by practice rank, then by name; staff after that."""
    return sorted(surgeons, key=_surgeon_sort_key)


def _next_physician_sort_order(db: Session) -> int:
    current_max = (
        db.query(func.max(Surgeon.sort_order))
        .filter(Surgeon.staff_type == "physician")
        .scalar()
        or 0
    )
    return int(current_max) + 10


# ── Dashboard ────────────────────────────────────────────────────────────────

def _is_no_call_reason(reason: str | None) -> bool:
    """DayOff reason 'No Call' (surgeon requested not to take call)."""
    if not reason:
        return False
    return " ".join(reason.strip().lower().split()) == "no call"


@router.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request, db: Session = Depends(get_db), admin=Depends(get_current_admin)):
    today = date.today()
    week_end = today + timedelta(days=7)

    on_call_today = [
        r for r in db.query(CallRotation).filter(CallRotation.date == today).all()
        if r.surgeon_id and surgeon_is_visible(r.surgeon)  # only show assigned (exclude NO call)
    ]

    pending_daysoff = [
        row for row in db.query(DayOff).filter(
            DayOff.status == "pending",
            DayOff.end_date >= today,
        ).order_by(DayOff.created_at.asc().nullsfirst(), DayOff.id.asc()).all()
        if surgeon_is_visible(row.surgeon)
    ]

    upcoming_meetings = [
        row
        for row in db.query(Meeting).filter(
            Meeting.date >= today,
            Meeting.date <= week_end,
        ).order_by(Meeting.date, Meeting.start_time).all()
        if not is_clinic_day_meeting(row)
    ][:5]
    from ..admin_settings_page_service import recent_admin_notifications, unread_admin_notification_count
    admin_notifications = recent_admin_notifications(db, admin.id, limit=8)
    admin_unread_notifications = unread_admin_notification_count(db, admin.id)

    surgeons = [row for row in db.query(Surgeon).filter(Surgeon.is_active == True).all() if surgeon_is_visible(row)]
    surgeons = _sort_surgeons_physicians_first(surgeons)
    active_count = len(surgeons)

    # Who is off today (approved day offs; No Call is separate — still available for clinic)
    off_today = db.query(DayOff).filter(
        DayOff.start_date <= today,
        DayOff.end_date >= today,
        DayOff.status == "approved",
    ).all()
    no_call_today = [
        d for d in off_today
        if _is_no_call_reason(d.reason) and surgeon_is_visible(d.surgeon)
    ]
    no_call_ids = {d.surgeon_id for d in no_call_today}
    off_ids = {
        d.surgeon_id for d in off_today
        if surgeon_is_visible(d.surgeon) and d.surgeon_id not in no_call_ids
    }
    available_count = active_count - len(off_ids)
    surgical_one_week = main_office_patients_by_weekday(db, today)
    aprima_sync = sync_status_payload(db)
    today_volume = dashboard_today_volume_stats(db, today)

    return templates.TemplateResponse("admin/dashboard.html", _base(
        request, admin, db=db,
        on_call_today=on_call_today,
        no_call_today=no_call_today,
        no_call_ids=no_call_ids,
        pending_daysoff=pending_daysoff,
        upcoming_meetings=upcoming_meetings,
        admin_notifications=admin_notifications,
        admin_unread_notifications=admin_unread_notifications,
        surgeons=surgeons,
        active_count=active_count,
        available_count=available_count,
        off_ids=off_ids,
        surgical_one_week=surgical_one_week,
        aprima_sync=aprima_sync,
        surgical_cases_today=today_volume["surgical_cases_today"],
        clinic_visits_today=today_volume["clinic_visits_today"],
    ))


@router.get("/aprima-sync-status")
def aprima_sync_status(
    db: Session = Depends(get_db),
    admin=Depends(get_current_admin),
):
    """JSON fingerprint for portal soft-refresh (no PHI)."""
    return sync_status_payload(db)


# ── Calendar ─────────────────────────────────────────────────────────────────

@router.get("/calendar", response_class=HTMLResponse)
def calendar(request: Request, db: Session = Depends(get_db), admin=Depends(get_current_admin)):
    surgeons = [
        row for row in db.query(Surgeon).filter(Surgeon.is_active == True).order_by(Surgeon.last_name).all()
        if surgeon_is_visible(row)
    ]
    surgeons = _sort_surgeons_physicians_first(surgeons)
    return templates.TemplateResponse("admin/calendar.html", _base(request, admin, db=db, surgeons=surgeons))


# ── Call Schedule ──────────────────────────────────────────────────────────────

def _call_schedule_qs(month_offset: int) -> str:
    return f"month_offset={month_offset}"


# ── Days Off ──────────────────────────────────────────────────────────────────
