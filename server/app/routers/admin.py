"""Admin portal HTML routes."""
import os
import urllib.parse
from datetime import date, timedelta

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..auth import (
    get_current_admin,
)
from ..database import get_db
from ..jinja_env import templates
from ..models import (
    AdminNotification, AdminUser, CallRotation, DayOff, Meeting, SiteSettings, Surgeon,
)
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

@router.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request, db: Session = Depends(get_db), admin=Depends(get_current_admin)):
    today = date.today()
    week_end = today + timedelta(days=7)

    on_call_today = [
        r for r in db.query(CallRotation).filter(CallRotation.date == today).all()
        if r.surgeon_id and surgeon_is_visible(r.surgeon)  # only show assigned (exclude NO call)
    ]

    pending_daysoff = [
        row for row in db.query(DayOff).filter(DayOff.status == "pending").all()
        if surgeon_is_visible(row.surgeon)
    ]

    upcoming_meetings = db.query(Meeting).filter(
        Meeting.date >= today,
        Meeting.date <= week_end,
    ).order_by(Meeting.date, Meeting.start_time).limit(5).all()
    admin_notifications = db.query(AdminNotification).filter(
        AdminNotification.admin_user_id == admin.id,
    ).order_by(AdminNotification.created_at.desc(), AdminNotification.id.desc()).limit(5).all()
    admin_unread_notifications = db.query(AdminNotification).filter(
        AdminNotification.admin_user_id == admin.id,
        AdminNotification.read_at.is_(None),
    ).count()

    surgeons = [row for row in db.query(Surgeon).filter(Surgeon.is_active == True).all() if surgeon_is_visible(row)]
    surgeons = _sort_surgeons_physicians_first(surgeons)
    active_count = len(surgeons)

    # Who is off today
    off_today = db.query(DayOff).filter(
        DayOff.start_date <= today,
        DayOff.end_date >= today,
        DayOff.status == "approved",
    ).all()
    off_ids = {d.surgeon_id for d in off_today if surgeon_is_visible(d.surgeon)}
    available_count = active_count - len(off_ids)

    return templates.TemplateResponse("admin/dashboard.html", _base(
        request, admin, db=db,
        on_call_today=on_call_today,
        pending_daysoff=pending_daysoff,
        upcoming_meetings=upcoming_meetings,
        admin_notifications=admin_notifications,
        admin_unread_notifications=admin_unread_notifications,
        surgeons=surgeons,
        active_count=active_count,
        available_count=available_count,
        off_ids=off_ids,
    ))


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
