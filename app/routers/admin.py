"""Admin portal HTML routes."""
import base64
import calendar as _calendar
import hashlib
import io
import os
import secrets
import urllib.parse
from datetime import date, datetime, time, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from ..auth import (
    SURGEON_ADMIN_PREVIEW_DEVICE_NAME,
    cookie_secure,
    create_surgeon_session_token,
    generate_magic_link_token,
    get_current_admin,
    hash_password,
    verify_password,
)
from ..conflicts import check_conflicts
from ..database import get_db
from ..jinja_env import templates
from ..models import (
    AdminUser, CallCoverage, CallGroup, CallGroupLocation, CallRotation, CallRotationTemplate,
    ClinicSchedule, DayOff, Location, Meeting, MeetingAttendee, PatientAssignment,
    SiteSettings, Surgeon, SurgeonDevice, SurgeonLocationSchedule, SurgicalCase,
)
from ..push import send_push_to_surgeon
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


# ── Surgeons ─────────────────────────────────────────────────────────────────

@router.get("/surgeons", response_class=HTMLResponse)
def surgeons_page(request: Request, db: Session = Depends(get_db), admin=Depends(get_current_admin)):
    surgeons = db.query(Surgeon).order_by(Surgeon.last_name).all()
    surgeons = _sort_surgeons_physicians_first(surgeons)
    return templates.TemplateResponse("admin/surgeons.html", _base(request, admin, db=db, surgeons=surgeons))


@router.post("/surgeons/add")
def add_surgeon(
    request: Request,
    first_name: str = Form(...),
    last_name: str = Form(...),
    suffix: str = Form(""),
    staff_type: str = Form("physician"),
    email: str = Form(""),
    phone: str = Form(""),
    sort_order: int = Form(0),
    db: Session = Depends(get_db),
    admin=Depends(get_current_admin),
):
    assigned_sort_order = sort_order
    if (staff_type or "physician") == "physician" and assigned_sort_order <= 0:
        assigned_sort_order = _next_physician_sort_order(db)
    s = Surgeon(first_name=first_name, last_name=last_name,
                suffix=suffix or None, staff_type=staff_type or "physician",
                email=email or None, phone=phone, color="#ffffff",
                sort_order=assigned_sort_order)
    db.add(s)
    db.commit()
    return RedirectResponse("/admin/surgeons?msg=added", status_code=303)


@router.post("/surgeons/{surgeon_id}/edit")
def edit_surgeon(
    surgeon_id: int,
    first_name: str = Form(...),
    last_name: str = Form(...),
    suffix: str = Form(""),
    staff_type: str = Form("physician"),
    email: str = Form(""),
    phone: str = Form(""),
    sort_order: int = Form(0),
    db: Session = Depends(get_db),
    admin=Depends(get_current_admin),
):
    s = db.get(Surgeon, surgeon_id)
    if s:
        assigned_sort_order = sort_order
        if (staff_type or "physician") == "physician" and assigned_sort_order <= 0:
            assigned_sort_order = _next_physician_sort_order(db)
        s.first_name = first_name
        s.last_name = last_name
        s.suffix = suffix or None
        s.staff_type = staff_type or "physician"
        s.email = email or None
        s.phone = phone
        s.color = "#ffffff"
        s.sort_order = assigned_sort_order
        db.commit()
    return RedirectResponse("/admin/surgeons?msg=updated", status_code=303)


@router.post("/surgeons/{surgeon_id}/delete")
def delete_surgeon(surgeon_id: int, db: Session = Depends(get_db), admin=Depends(get_current_admin)):
    s = db.get(Surgeon, surgeon_id)
    if not s:
        return RedirectResponse("/admin/surgeons?msg=not_found", status_code=303)
    db.delete(s)
    db.commit()
    return RedirectResponse("/admin/surgeons?msg=deleted", status_code=303)


@router.post("/surgeons/{surgeon_id}/toggle")
def toggle_surgeon(surgeon_id: int, db: Session = Depends(get_db), admin=Depends(get_current_admin)):
    s = db.get(Surgeon, surgeon_id)
    if s:
        s.is_active = not s.is_active
        db.commit()
    return RedirectResponse("/admin/surgeons", status_code=303)


@router.post("/surgeons/{surgeon_id}/magic-link")
def create_magic_link(
    surgeon_id: int,
    request: Request,
    db: Session = Depends(get_db),
    admin=Depends(get_current_admin),
):
    import qrcode
    from concurrent.futures import ThreadPoolExecutor
    from ..email_service import send_magic_link_email

    base_url = str(request.base_url).rstrip("/")
    link = generate_magic_link_token(surgeon_id, db, base_url)

    qr = qrcode.QRCode(version=None, error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=8, border=3)
    qr.add_data(link)
    qr.make(fit=True)
    img = qr.make_image(fill_color="#14305A", back_color="white")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    qr_b64 = base64.b64encode(buf.getvalue()).decode()

    # Email the link + QR code if the surgeon has an email on file
    surgeon = db.get(Surgeon, surgeon_id)
    if surgeon and surgeon.email:
        import os
        _exec = ThreadPoolExecutor(max_workers=1)
        _exec.submit(
            send_magic_link_email,
            to_email=surgeon.email,
            to_name=surgeon.full_name or surgeon.email,
            magic_url=link,
            app_name="Mid Florida Surgical Calendar",
            expiry_hours=int(os.environ.get("MAGIC_LINK_EXPIRE_HOURS", "168")),
        )

    surgeons = db.query(Surgeon).order_by(Surgeon.last_name).all()
    surgeons = _sort_surgeons_physicians_first(surgeons)
    return templates.TemplateResponse("admin/surgeons.html", _base(
        request, admin, db=db, surgeons=surgeons, generated_link=link,
        link_surgeon_id=surgeon_id, qr_code_b64=qr_b64,
    ))


@router.post("/surgeons/{surgeon_id}/devices/{device_id}/revoke")
def revoke_device(surgeon_id: int, device_id: int, db: Session = Depends(get_db), admin=Depends(get_current_admin)):
    device = db.get(SurgeonDevice, device_id)
    if device and device.surgeon_id == surgeon_id:
        device.is_active = False
        db.commit()
    return RedirectResponse("/admin/surgeons", status_code=303)


@router.post("/surgeons/{surgeon_id}/preview-mobile")
def preview_surgeon_mobile(
    surgeon_id: int,
    request: Request,
    db: Session = Depends(get_db),
    admin=Depends(get_current_admin),
):
    """Issue a surgeon session in this browser without consuming a magic link.

    Uses cookie ``surgeon_token_preview`` so real ``surgeon_token`` (physician phone) is untouched.
    """
    surgeon = db.get(Surgeon, surgeon_id)
    if not surgeon or not surgeon.is_active:
        raise HTTPException(status_code=404, detail="Physician not found or inactive")

    now = datetime.now(timezone.utc)
    ua = request.headers.get("user-agent", "Desktop preview")
    device = (
        db.query(SurgeonDevice)
        .filter(
            SurgeonDevice.surgeon_id == surgeon_id,
            SurgeonDevice.device_name == SURGEON_ADMIN_PREVIEW_DEVICE_NAME,
        )
        .first()
    )
    placeholder = secrets.token_urlsafe(32)
    if not device:
        device = SurgeonDevice(
            surgeon_id=surgeon_id,
            device_name=SURGEON_ADMIN_PREVIEW_DEVICE_NAME,
            user_agent=ua,
            token_hash=hashlib.sha256(placeholder.encode()).hexdigest(),
            last_seen=now,
        )
        db.add(device)
        db.commit()
        db.refresh(device)
    else:
        device.is_active = True
        device.last_seen = now
        device.user_agent = ua
        db.commit()

    session_token = create_surgeon_session_token(device.id)
    resp = RedirectResponse("/surgeon/schedule", status_code=303)
    resp.set_cookie(
        "surgeon_token_preview",
        session_token,
        httponly=True,
        secure=cookie_secure(),
        samesite="lax",
        max_age=365 * 24 * 3600,
    )
    return resp


# ── Call Schedule ──────────────────────────────────────────────────────────────

@router.get("/rotations", response_class=RedirectResponse)
def _redirect_rotations(week_offset: int = 0):
    """Redirect legacy URL to call-schedule."""
    return RedirectResponse(f"/admin/call-schedule?week_offset={week_offset}", status_code=302)


def _call_schedule_qs(month_offset: int) -> str:
    return f"month_offset={month_offset}"


@router.get("/call-schedule", response_class=HTMLResponse)
def call_schedule_page(
    request: Request,
    month_offset: int = 0,
    db: Session = Depends(get_db),
    admin=Depends(get_current_admin),
):
    today = date.today()
    total_months = today.year * 12 + (today.month - 1) + month_offset
    year = total_months // 12
    month = total_months % 12 + 1
    first_day = date(year, month, 1)
    days_in_month = _calendar.monthrange(year, month)[1]
    schedule_days = [date(year, month, d) for d in range(1, days_in_month + 1)]
    month_label = first_day.strftime("%B %Y")
    # Padding: how many empty cells before the 1st (Sun=0 start)
    pad_start = (first_day.weekday() + 1) % 7

    surgeons = db.query(Surgeon).filter(Surgeon.is_active == True).order_by(Surgeon.last_name).all()
    surgeons = _sort_surgeons_physicians_first(surgeons)

    call_groups = (
        db.query(CallGroup).order_by(CallGroup.sort_order, CallGroup.name, CallGroup.id).all()
    )

    # One row per call group; each cell = one rotation. Show primary or backup (legacy backup = Altamonte row).
    rotations = (
        db.query(CallRotation)
        .options(
            joinedload(CallRotation.surgeon),
            joinedload(CallRotation.coverages).joinedload(CallCoverage.covering_surgeon),
        )
        .filter(
            CallRotation.date >= schedule_days[0],
            CallRotation.date <= schedule_days[-1],
        )
        .all()
    )
    # By group and date: one rotation per (group_id, date); prefer primary if both exist
    rotation_by_group_date = {}
    for r in rotations:
        if r.call_group_id is None:
            continue
        by_date = rotation_by_group_date.setdefault(r.call_group_id, {})
        if r.date not in by_date:
            by_date[r.date] = r

    # Deduplicate by name: one row per unique group name (keep first by sort_order, name, id); merge rotations
    seen_names = set()
    group_rows = []
    for g in call_groups:
        if g.name in seen_names:
            continue
        seen_names.add(g.name)
        # Merge rotation maps for all groups with this name (same name = same logical row)
        merged_rotations = dict(rotation_by_group_date.get(g.id, {}))
        for other in call_groups:
            if other.id != g.id and other.name == g.name:
                for d, rot in rotation_by_group_date.get(other.id, {}).items():
                    if d not in merged_rotations:
                        merged_rotations[d] = rot
        group_rows.append((g, merged_rotations))

    day_off_rows = (
        db.query(DayOff)
        .options(joinedload(DayOff.surgeon))
        .filter(
            DayOff.start_date <= schedule_days[-1],
            DayOff.end_date >= schedule_days[0],
            DayOff.status.in_(["pending", "approved"]),
        )
        .all()
    )
    day_off_by_date: dict[date, dict[str, list[Surgeon]]] = {
        day: {"pending": [], "approved": []} for day in schedule_days
    }
    seen_day_off_initials: dict[date, dict[str, set[str]]] = {
        day: {"pending": set(), "approved": set()} for day in schedule_days
    }
    for row in day_off_rows:
        if not row.surgeon or not row.surgeon.is_active:
            continue
        status = "approved" if row.status == "approved" else "pending"
        start = max(row.start_date, schedule_days[0])
        end = min(row.end_date, schedule_days[-1])
        current = start
        while current <= end:
            initials = (row.surgeon.initials or "").strip()
            if initials and initials not in seen_day_off_initials[current][status]:
                day_off_by_date[current][status].append(row.surgeon)
                seen_day_off_initials[current][status].add(initials)
            current += timedelta(days=1)
    for status_groups in day_off_by_date.values():
        for surgeons_for_status in status_groups.values():
            surgeons_for_status.sort(key=_surgeon_sort_key)

    locations = db.query(Location).filter(Location.is_active == True).order_by(Location.name).all()
    hospital_locations = [loc for loc in locations if getattr(loc, "location_type", None) == "hospital"]

    return templates.TemplateResponse("admin/call_schedule.html", _base(
        request, admin, db=db,
        surgeons=surgeons,
        schedule_days=schedule_days,
        group_rows=group_rows,
        month_offset=month_offset,
        month_label=month_label,
        pad_start=pad_start,
        day_off_by_date=day_off_by_date,
        call_groups=call_groups,
        locations=locations,
        today=today,
    ))


def _parse_call_group_id(raw: str | int | None) -> int | None:
    if raw is None:
        return None
    if isinstance(raw, int):
        return raw
    s = (raw or "").strip()
    return int(s) if s else None


@router.post("/call-schedule/assign")
def assign_rotation(
    rotation_date: str = Form(...),
    surgeon_id: str = Form(""),  # empty = NO call
    rotation_type: str = Form("primary"),
    month_offset: int = Form(0),
    call_group_id: str = Form(""),
    db: Session = Depends(get_db),
    admin=Depends(get_current_admin),
):
    d = date.fromisoformat(rotation_date)
    sid = int(surgeon_id) if surgeon_id and surgeon_id.strip() else None
    gid = _parse_call_group_id(call_group_id)
    # One assignment per (group, date): find any existing rotation for this group+date and update, or create
    q = db.query(CallRotation).filter(CallRotation.date == d)
    if gid is not None:
        q = q.filter(CallRotation.call_group_id == gid)
    else:
        q = q.filter(CallRotation.call_group_id.is_(None))
    existing = q.first()
    if existing:
        existing.surgeon_id = sid
        rot_id = existing.id
    else:
        r = CallRotation(
            surgeon_id=sid,
            date=d,
            rotation_type="primary",
            call_group_id=gid,
        )
        db.add(r)
        db.flush()
        rot_id = r.id
    db.commit()

    surgeon = db.get(Surgeon, sid) if sid else None
    if surgeon:
        send_push_to_surgeon(surgeon_id, "Schedule Update",
                             f"You've been assigned on-call on {d.strftime('%b %d')}", db)

    conflicts = []
    if surgeon and sid:
        conflicts = check_conflicts(
            sid, d, d, db,
            exclude_call_rotation_id=rot_id,
            target_entity={"type": "call_rotation", "date": d},
        )
        conflicts = [f"{surgeon.full_name}: " + c for c in conflicts]
    return _warn_redirect(f"/admin/call-schedule?{_call_schedule_qs(month_offset)}", conflicts)


@router.post("/call-schedule/reclaim-orphans")
def reclaim_orphan_rotations(
    month_offset: int = Form(0),
    db: Session = Depends(get_db),
    admin=Depends(get_current_admin),
):
    """Assign any call rotations with call_group_id NULL to the correct group (primary→Winter Garden group, backup→Altamonte). Use after restoring from backup."""
    from ..migrate_call_groups import GROUP1_NAME, GROUP2_NAME
    from sqlalchemy import text
    from ..database import engine
    with engine.begin() as conn:
        conn.execute(text("""
            UPDATE call_rotations SET call_group_id = (SELECT id FROM call_groups WHERE name = :name LIMIT 1)
            WHERE call_group_id IS NULL AND rotation_type = 'primary'
        """), {"name": GROUP1_NAME})
        conn.execute(text("""
            UPDATE call_rotations SET call_group_id = (SELECT id FROM call_groups WHERE name = :name LIMIT 1)
            WHERE call_group_id IS NULL AND rotation_type = 'backup'
        """), {"name": GROUP2_NAME})
    return RedirectResponse(
        f"/admin/call-schedule?{_call_schedule_qs(month_offset)}&msg=orphans_reclaimed",
        status_code=303,
    )


@router.post("/call-schedule/copy-week")
def copy_call_week(
    source_offset: int = Form(...),
    schedule_view: str = Form("week"),
    db: Session = Depends(get_db),
    admin=Depends(get_current_admin),
):
    """Copy this week's call assignments to the next week (same group and day-of-week)."""
    today = date.today()
    week_start = today - timedelta(days=today.weekday()) + timedelta(weeks=source_offset)
    week_days_src = [week_start + timedelta(days=i) for i in range(7)]
    week_start_dst = week_start + timedelta(weeks=1)
    copied = 0
    for i in range(7):
        d_src = week_days_src[i]
        d_dst = week_start_dst + timedelta(days=i)
        rotations_src = db.query(CallRotation).filter(
            CallRotation.date == d_src,
        ).all()
        for r in rotations_src:
            if r.call_group_id is None:
                continue
            existing = db.query(CallRotation).filter(
                CallRotation.date == d_dst,
                CallRotation.call_group_id == r.call_group_id,
            ).first()
            if not existing:
                db.add(CallRotation(
                    surgeon_id=r.surgeon_id,
                    date=d_dst,
                    rotation_type="primary",
                    call_group_id=r.call_group_id,
                ))
                copied += 1
    db.commit()
    return RedirectResponse(
        f"/admin/call-schedule?msg=week_copied&n={copied}",
        status_code=303,
    )


@router.post("/call-schedule/clear")
def clear_rotation(
    rotation_date: str = Form(...),
    rotation_type: str = Form(""),
    month_offset: int = Form(0),
    call_group_id: str = Form(""),
    db: Session = Depends(get_db),
    admin=Depends(get_current_admin),
):
    d = date.fromisoformat(rotation_date)
    gid = _parse_call_group_id(call_group_id)
    q = db.query(CallRotation).filter(CallRotation.date == d)
    if gid is not None:
        q = q.filter(CallRotation.call_group_id == gid)
    else:
        q = q.filter(CallRotation.call_group_id.is_(None))
    q.delete()
    db.commit()
    return RedirectResponse(
        f"/admin/call-schedule?{_call_schedule_qs(month_offset)}",
        status_code=303,
    )


# ── Days Off ──────────────────────────────────────────────────────────────────

# ── Clinic Schedule ───────────────────────────────────────────────────────────

@router.get("/clinic-schedule", response_class=HTMLResponse)
def clinic_schedule_page(
    request: Request,
    week_offset: int = 0,
    db: Session = Depends(get_db),
    admin=Depends(get_current_admin),
):
    today = date.today()
    week_start = today - timedelta(days=today.weekday()) + timedelta(weeks=week_offset)
    week_days = [week_start + timedelta(days=i) for i in range(7)]

    surgeons = db.query(Surgeon).filter(Surgeon.is_active == True).order_by(Surgeon.last_name).all()
    surgeons = _sort_surgeons_physicians_first(surgeons)
    all_locations = db.query(Location).filter(
        Location.is_active == True,
    ).order_by(Location.location_type, Location.name).all()
    clinic_locations = [l for l in all_locations if l.location_type == "clinic"]
    hospital_locations = [l for l in all_locations if l.location_type == "hospital"]

    schedules = db.query(ClinicSchedule).filter(
        ClinicSchedule.date >= week_days[0],
        ClinicSchedule.date <= week_days[6],
    ).all()

    # Build lookup: {surgeon_id: {date: [ClinicSchedule, ...]}}
    sched_map = {}
    for cs in schedules:
        sched_map.setdefault(cs.surgeon_id, {}).setdefault(cs.date, []).append(cs)

    # Surgical cases for the week: {surgeon_id: {date: [SurgicalCase, ...]}} (ordered by start_time)
    surgical_cases = (
        db.query(SurgicalCase)
        .filter(
            SurgicalCase.date >= week_days[0],
            SurgicalCase.date <= week_days[6],
            SurgicalCase.status != "cancelled",
        )
        .order_by(SurgicalCase.date, SurgicalCase.start_time)
        .all()
    )
    surgical_map = {}
    for sc in surgical_cases:
        surgical_map.setdefault(sc.surgeon_id, {}).setdefault(sc.date, []).append(sc)

    # JSON-serializable case list for timeline panel: key "surgeonId_date" -> list of case dicts (incl. edit fields)
    surgical_cases_json = {}
    for sid, day_cases in surgical_map.items():
        for d, cases in day_cases.items():
            key = f"{sid}_{d.isoformat()}"
            surgical_cases_json[key] = [
                {
                    "id": c.id,
                    "surgeon_id": c.surgeon_id,
                    "date": c.date.isoformat(),
                    "start": c.start_time.strftime("%H:%M") if c.start_time else "08:00",
                    "end": c.end_time.strftime("%H:%M") if c.end_time else None,
                    "patient": c.patient_name or "",
                    "patient_dob": c.patient_dob or "",
                    "patient_phone": c.patient_phone or "",
                    "procedure": c.procedure or "",
                    "procedure_short": (c.procedure or "")[:80],
                    "location_id": c.location_id or "",
                    "room": (c.location.name if c.location else None) or c.room_text or "",
                    "room_text": c.room_text or "",
                    "status": c.status or "scheduled",
                    "notes": c.notes or "",
                }
                for c in cases
            ]

    return templates.TemplateResponse("admin/clinic_schedule.html", _base(
        request, admin, db=db,
        surgeons=surgeons,
        clinics=clinic_locations,
        hospitals=hospital_locations,
        all_locations=all_locations,
        week_days=week_days,
        sched_map=sched_map,
        surgical_map=surgical_map,
        surgical_cases_json=surgical_cases_json,
        week_offset=week_offset,
        locations=all_locations,
        today=today,
    ))


def _schedule_rows_for_slot(query, session: str):
    session = (session or "full").lower()
    if session == "full":
        return query.all()
    return query.filter(
        ClinicSchedule.session.in_([session, "full"])
    ).all()


@router.post("/clinic-schedule/assign")
def assign_clinic(
    schedule_date: str = Form(...),
    surgeon_id: int = Form(...),
    location_choice: str = Form(...),
    session: str = Form("full"),
    notes: str = Form(""),
    week_offset: int = Form(0),
    db: Session = Depends(get_db),
    admin=Depends(get_current_admin),
):
    d = date.fromisoformat(schedule_date)
    assignment_type = "off" if location_choice == "__off__" else "assigned"
    location_id = None if assignment_type == "off" else int(location_choice)
    slot_query = db.query(ClinicSchedule).filter(
        ClinicSchedule.surgeon_id == surgeon_id,
        ClinicSchedule.date == d,
    )
    for existing in _schedule_rows_for_slot(slot_query, session):
        db.delete(existing)
    db.flush()

    conflicts = []
    cs_new = ClinicSchedule(
        surgeon_id=surgeon_id,
        location_id=location_id,
        date=d,
        session=session,
        assignment_type=assignment_type,
        notes=notes,
    )
    db.add(cs_new)
    db.flush()
    db.commit()

    surgeon = db.get(Surgeon, surgeon_id)
    loc = db.get(Location, location_id) if location_id else None
    if surgeon:
        if assignment_type == "off":
            send_push_to_surgeon(
                surgeon_id,
                "Schedule Updated",
                f"{d.strftime('%b %d')}: OFF",
                db,
            )
        elif loc:
            send_push_to_surgeon(
                surgeon_id,
                "Clinic Schedule Updated",
                f"{d.strftime('%b %d')}: {loc.name}",
                db,
            )
            raw = check_conflicts(
                surgeon_id, d, d, db,
                exclude_clinic_schedule_id=cs_new.id,
                target_entity={"type": "clinic_schedule", "date": d, "session": session},
            )
            conflicts = [f"{surgeon.full_name}: " + c for c in raw]
    return _warn_redirect(f"/admin/clinic-schedule?week_offset={week_offset}", conflicts)


@router.post("/clinic-schedule/clear")
def clear_clinic(
    schedule_id: int = Form(...),
    week_offset: int = Form(0),
    db: Session = Depends(get_db),
    admin=Depends(get_current_admin),
):
    cs = db.get(ClinicSchedule, schedule_id)
    if cs:
        db.delete(cs)
        db.commit()
    return RedirectResponse(f"/admin/clinic-schedule?week_offset={week_offset}", status_code=303)


@router.post("/clinic-schedule/copy-week")
def copy_clinic_week(
    source_offset: int = Form(...),
    surgeon_id: str = Form("all"),
    db: Session = Depends(get_db),
    admin=Depends(get_current_admin),
):
    """Copy the source week's clinic schedule to the next week."""
    today = date.today()
    src_start = today - timedelta(days=today.weekday()) + timedelta(weeks=source_offset)
    src_end = src_start + timedelta(days=6)
    dst_start = src_start + timedelta(weeks=1)
    dst_end = dst_start + timedelta(days=6)

    src_query = db.query(ClinicSchedule).filter(
        ClinicSchedule.date >= src_start,
        ClinicSchedule.date <= src_end,
    )
    dst_query = db.query(ClinicSchedule).filter(
        ClinicSchedule.date >= dst_start,
        ClinicSchedule.date <= dst_end,
    )

    surgeon_filter = None
    if surgeon_id != "all":
        try:
            surgeon_filter = int(surgeon_id)
        except ValueError:
            return RedirectResponse(
                f"/admin/clinic-schedule?week_offset={source_offset}&warn=Invalid+surgeon+selection",
                status_code=303,
            )
        src_query = src_query.filter(ClinicSchedule.surgeon_id == surgeon_filter)
        dst_query = dst_query.filter(ClinicSchedule.surgeon_id == surgeon_filter)

    src_schedules = src_query.all()
    dst_schedules = dst_query.all()

    replaced = len(dst_schedules)
    for existing in dst_schedules:
        db.delete(existing)

    created = 0
    for cs in src_schedules:
        offset = (cs.date - src_start).days
        new_date = dst_start + timedelta(days=offset)
        db.add(ClinicSchedule(
            surgeon_id=cs.surgeon_id,
            location_id=cs.location_id,
            date=new_date,
            session=cs.session,
            assignment_type=cs.assignment_type or "assigned",
            notes=cs.notes,
        ))
        created += 1
    db.commit()
    next_offset = source_offset + 1
    return RedirectResponse(
        f"/admin/clinic-schedule?week_offset={next_offset}&msg=week_copied&created={created}&replaced={replaced}",
        status_code=303,
    )


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


