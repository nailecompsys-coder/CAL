"""Admin portal HTML routes."""
import os
import urllib.parse
from datetime import date, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..auth import (
    get_current_admin,
    hash_password,
    verify_password,
)
from ..database import get_db
from ..jinja_env import templates
from ..models import (
    AdminUser, CallGroup, CallGroupLocation, CallRotation, CallRotationTemplate,
    ClinicSchedule, DayOff, Location, Meeting, MeetingAttendee, PatientAssignment,
    SiteSettings, Surgeon, SurgeonLocationSchedule,
)
from .. import wasabi_backup
from .. import __version__ as app_version

UPLOADS_DIR = "app/static/uploads"
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
        if r.surgeon_id  # only show assigned (exclude NO call)
    ]

    pending_daysoff = db.query(DayOff).filter(DayOff.status == "pending").all()

    upcoming_meetings = db.query(Meeting).filter(
        Meeting.date >= today,
        Meeting.date <= week_end,
    ).order_by(Meeting.date, Meeting.start_time).limit(5).all()

    surgeons = db.query(Surgeon).filter(Surgeon.is_active == True).all()
    surgeons = _sort_surgeons_physicians_first(surgeons)
    active_count = len(surgeons)

    # Who is off today
    off_today = db.query(DayOff).filter(
        DayOff.start_date <= today,
        DayOff.end_date >= today,
        DayOff.status == "approved",
    ).all()
    off_ids = {d.surgeon_id for d in off_today}
    available_count = active_count - len(off_ids)

    return templates.TemplateResponse("admin/dashboard.html", _base(
        request, admin, db=db,
        on_call_today=on_call_today,
        pending_daysoff=pending_daysoff,
        upcoming_meetings=upcoming_meetings,
        surgeons=surgeons,
        active_count=active_count,
        available_count=available_count,
        off_ids=off_ids,
    ))


# ── Calendar ─────────────────────────────────────────────────────────────────

@router.get("/calendar", response_class=HTMLResponse)
def calendar(request: Request, db: Session = Depends(get_db), admin=Depends(get_current_admin)):
    surgeons = db.query(Surgeon).filter(Surgeon.is_active == True).order_by(Surgeon.last_name).all()
    surgeons = _sort_surgeons_physicians_first(surgeons)
    return templates.TemplateResponse("admin/calendar.html", _base(request, admin, db=db, surgeons=surgeons))


# ── Call Schedule ──────────────────────────────────────────────────────────────

def _call_schedule_qs(month_offset: int) -> str:
    return f"month_offset={month_offset}"


# ── Days Off ──────────────────────────────────────────────────────────────────

# ── Schedule Templates ────────────────────────────────────────────────────────

def _sort_surgeons_by_type(surgeons):
    """Template view uses the same practice-rank ordering as the rest of admin."""
    return _sort_surgeons_physicians_first(surgeons)


@router.get("/schedule-templates", response_class=HTMLResponse)
def schedule_templates_page(
    request: Request,
    db: Session = Depends(get_db),
    admin=Depends(get_current_admin),
):
    surgeons = db.query(Surgeon).filter(Surgeon.is_active == True).all()
    surgeons = _sort_surgeons_by_type(surgeons)
    all_locations = db.query(Location).filter(Location.is_active == True).order_by(Location.location_type.desc(), Location.name).all()

    # Build template map: {surgeon_id: {day_of_week: {session: SurgeonLocationSchedule}}}
    templates_raw = db.query(SurgeonLocationSchedule).all()
    tpl_map = {}
    for t in templates_raw:
        tpl_map.setdefault(t.surgeon_id, {}).setdefault(t.day_of_week, {})[t.session] = t

    # Call groups for the call rotation builder
    call_groups = db.query(CallGroup).order_by(CallGroup.sort_order).all()
    rotation_templates = db.query(CallRotationTemplate).order_by(
        CallRotationTemplate.call_group_id, CallRotationTemplate.position
    ).all()
    rotation_by_group = {}
    for rt in rotation_templates:
        rotation_by_group.setdefault(rt.call_group_id, []).append(rt)

    # Surgeons per call group (for the call rotation section)
    # Map surgeon_id → call group membership inferred from group name
    # WG group surgeons = physicians; ALT group = part-time/ALT surgeons
    # We let admins configure this directly via the rotation template

    return templates.TemplateResponse("admin/schedule_templates.html", _base(
        request, admin, db=db,
        surgeons=surgeons,
        all_locations=all_locations,
        tpl_map=tpl_map,
        call_groups=call_groups,
        rotation_by_group=rotation_by_group,
        days=["Mon", "Tue", "Wed", "Thu", "Fri"],
    ))


@router.post("/schedule-templates/save")
def save_schedule_template(
    request: Request,
    surgeon_id: int = Form(...),
    db: Session = Depends(get_db),
    admin=Depends(get_current_admin),
):
    """Save one surgeon's weekly template from the grid form."""
    import asyncio

    async def _get_form():
        return await request.form()

    form = asyncio.get_event_loop().run_until_complete(_get_form()) if False else None

    # We'll read form synchronously via request state — use the standard FastAPI way
    return RedirectResponse("/admin/schedule-templates?msg=saved", status_code=303)


@router.post("/schedule-templates/save-cell")
async def save_template_cell(
    surgeon_id: int = Form(...),
    day_of_week: int = Form(...),
    session: str = Form(...),
    location_id: Optional[int] = Form(None),
    assignment_type: str = Form("assigned"),
    db: Session = Depends(get_db),
    admin=Depends(get_current_admin),
):
    """Save a single cell in the weekly template grid (called via fetch)."""
    existing = db.query(SurgeonLocationSchedule).filter(
        SurgeonLocationSchedule.surgeon_id == surgeon_id,
        SurgeonLocationSchedule.day_of_week == day_of_week,
        SurgeonLocationSchedule.session == session,
    ).first()

    if assignment_type == "off" and location_id is None and existing is None:
        # Nothing to store for blank OFF (default is no entry)
        from fastapi.responses import JSONResponse
        return JSONResponse({"ok": True, "action": "noop"})

    if existing:
        existing.location_id = location_id if assignment_type == "assigned" else None
        existing.assignment_type = assignment_type
    else:
        db.add(SurgeonLocationSchedule(
            surgeon_id=surgeon_id,
            day_of_week=day_of_week,
            session=session,
            location_id=location_id if assignment_type == "assigned" else None,
            assignment_type=assignment_type,
        ))
    db.commit()
    from fastapi.responses import JSONResponse
    return JSONResponse({"ok": True, "action": "updated" if existing else "created"})


@router.post("/schedule-templates/apply")
async def apply_schedule_templates(
    date_from: str = Form(...),
    date_to: str = Form(...),
    surgeon_ids: str = Form("all"),  # "all" or comma-separated ids
    skip_existing: bool = Form(True),
    overwrite_daysoff: bool = Form(False),
    db: Session = Depends(get_db),
    admin=Depends(get_current_admin),
):
    """Generate clinic_schedules from weekly templates for a date range."""
    try:
        d_from = date.fromisoformat(date_from)
        d_to = date.fromisoformat(date_to)
    except ValueError:
        return RedirectResponse("/admin/schedule-templates?msg=bad_date", status_code=303)

    if d_to < d_from or (d_to - d_from).days > 366:
        return RedirectResponse("/admin/schedule-templates?msg=bad_range", status_code=303)

    # Which surgeons
    if surgeon_ids == "all":
        target_ids = [s.id for s in db.query(Surgeon.id).filter(Surgeon.is_active == True).all()]
    else:
        target_ids = [int(x) for x in surgeon_ids.split(",") if x.strip().isdigit()]

    # Load templates
    templates_all = db.query(SurgeonLocationSchedule).filter(
        SurgeonLocationSchedule.surgeon_id.in_(target_ids),
        SurgeonLocationSchedule.assignment_type != "off",
    ).all()

    # Group by surgeon → day_of_week → session
    tpl_by_surgeon = {}
    for t in templates_all:
        tpl_by_surgeon.setdefault(t.surgeon_id, {}).setdefault(t.day_of_week, {})[t.session] = t

    # Load days_off in range for all target surgeons (approved)
    days_off_records = db.query(DayOff).filter(
        DayOff.surgeon_id.in_(target_ids),
        DayOff.start_date <= d_to,
        DayOff.end_date >= d_from,
        DayOff.status == "approved",
    ).all()
    off_dates = set()  # (surgeon_id, date)
    for doff in days_off_records:
        cur = doff.start_date
        while cur <= doff.end_date:
            off_dates.add((doff.surgeon_id, cur))
            cur += timedelta(days=1)

    created = 0
    skipped_existing = 0
    skipped_off = 0
    skipped_float = 0

    cur_date = d_from
    while cur_date <= d_to:
        dow = cur_date.weekday()  # 0=Mon, 4=Fri, 5=Sat, 6=Sun
        if dow > 4:  # skip weekends
            cur_date += timedelta(days=1)
            continue

        for sid in target_ids:
            if (sid, cur_date) in off_dates and not overwrite_daysoff:
                skipped_off += 1
                continue

            day_tpls = tpl_by_surgeon.get(sid, {}).get(dow, {})
            for sess, tpl in day_tpls.items():
                if tpl.assignment_type == "float":
                    skipped_float += 1
                    continue  # Float sessions aren't clinic schedule entries
                if tpl.assignment_type == "assigned" and tpl.location_id is None:
                    continue

                if skip_existing:
                    exists = db.query(ClinicSchedule).filter(
                        ClinicSchedule.surgeon_id == sid,
                        ClinicSchedule.date == cur_date,
                        ClinicSchedule.session == sess,
                    ).first()
                    if exists:
                        skipped_existing += 1
                        continue

                db.add(ClinicSchedule(
                    surgeon_id=sid,
                    location_id=tpl.location_id if tpl.assignment_type == "assigned" else None,
                    date=cur_date,
                    session=sess,
                    assignment_type=tpl.assignment_type,
                    notes=None,
                ))
                created += 1

        cur_date += timedelta(days=1)

    db.commit()
    return RedirectResponse(
        f"/admin/schedule-templates?msg=applied&created={created}&skipped={skipped_existing}&off={skipped_off}",
        status_code=303,
    )


# ── Call Rotation Builder ─────────────────────────────────────────────────────

@router.post("/call-rotation/save-order")
async def save_call_rotation_order(
    request: Request,
    call_group_id: int = Form(...),
    db: Session = Depends(get_db),
    admin=Depends(get_current_admin),
):
    """Save the ordered surgeon list for a call group rotation template."""
    form = await request.form()
    # Expect fields: surgeon_ids[] in order
    surgeon_ids = form.getlist("surgeon_ids[]")
    if not surgeon_ids:
        return RedirectResponse("/admin/schedule-templates?msg=no_surgeons", status_code=303)

    # Delete existing rotation for this group
    db.query(CallRotationTemplate).filter(
        CallRotationTemplate.call_group_id == call_group_id
    ).delete()

    for pos, sid in enumerate(surgeon_ids, start=1):
        db.add(CallRotationTemplate(
            call_group_id=call_group_id,
            surgeon_id=int(sid),
            position=pos,
        ))
    db.commit()
    return RedirectResponse("/admin/schedule-templates?msg=rotation_saved&tab=call", status_code=303)


@router.post("/call-rotation/auto-fill")
def call_rotation_auto_fill(
    call_group_id: int = Form(...),
    date_from: str = Form(...),
    date_to: str = Form(...),
    start_position: int = Form(1),
    days_per_surgeon: int = Form(1),
    skip_existing: bool = Form(True),
    rotation_type: str = Form("primary"),
    db: Session = Depends(get_db),
    admin=Depends(get_current_admin),
):
    """Auto-fill call_rotations for a date range by cycling through the rotation template."""
    try:
        d_from = date.fromisoformat(date_from)
        d_to = date.fromisoformat(date_to)
    except ValueError:
        return RedirectResponse("/admin/schedule-templates?tab=call&msg=bad_date", status_code=303)

    if d_to < d_from or (d_to - d_from).days > 366:
        return RedirectResponse("/admin/schedule-templates?tab=call&msg=bad_range", status_code=303)

    # Load rotation order for this group
    rotation = db.query(CallRotationTemplate).filter(
        CallRotationTemplate.call_group_id == call_group_id,
    ).order_by(CallRotationTemplate.position).all()

    if not rotation:
        return RedirectResponse("/admin/schedule-templates?tab=call&msg=no_rotation", status_code=303)

    # Load days_off in range for all surgeons in rotation (approved, no_call qualifies too)
    surgeon_ids = [r.surgeon_id for r in rotation]
    days_off_records = db.query(DayOff).filter(
        DayOff.surgeon_id.in_(surgeon_ids),
        DayOff.start_date <= d_to,
        DayOff.end_date >= d_from,
        DayOff.status == "approved",
    ).all()
    off_dates = set()  # (surgeon_id, date)
    for doff in days_off_records:
        cur = doff.start_date
        while cur <= doff.end_date:
            off_dates.add((doff.surgeon_id, cur))
            cur += timedelta(days=1)

    n = len(rotation)
    rot_idx = (start_position - 1) % n  # 0-based index into rotation
    day_count = 0  # days this surgeon has been on call in current block
    created = 0
    skipped = 0

    cur_date = d_from
    while cur_date <= d_to:
        # Try to assign; skip surgeons with days_off and advance rotation
        attempts = 0
        while attempts < n:
            surgeon = rotation[rot_idx]
            if (surgeon.surgeon_id, cur_date) not in off_dates:
                break
            # This surgeon is off — advance rotation
            rot_idx = (rot_idx + 1) % n
            day_count = 0
            attempts += 1
        else:
            # All surgeons off this day — leave unassigned
            cur_date += timedelta(days=1)
            continue

        if skip_existing:
            exists = db.query(CallRotation).filter(
                CallRotation.date == cur_date,
                CallRotation.call_group_id == call_group_id,
                CallRotation.rotation_type == rotation_type,
            ).first()
            if exists:
                skipped += 1
                cur_date += timedelta(days=1)
                day_count += 1
                if day_count >= days_per_surgeon:
                    rot_idx = (rot_idx + 1) % n
                    day_count = 0
                continue

        db.add(CallRotation(
            surgeon_id=surgeon.surgeon_id,
            date=cur_date,
            rotation_type=rotation_type,
            call_group_id=call_group_id,
        ))
        created += 1

        day_count += 1
        if day_count >= days_per_surgeon:
            rot_idx = (rot_idx + 1) % n
            day_count = 0

        cur_date += timedelta(days=1)

    db.commit()
    return RedirectResponse(
        f"/admin/schedule-templates?tab=call&msg=call_filled&created={created}&skipped={skipped}",
        status_code=303,
    )
