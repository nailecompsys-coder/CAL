"""Surgeon PWA HTML routes."""
import calendar as _cal
import json as _json
import urllib.parse
from collections import defaultdict
from datetime import date, datetime, time as time_type, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import func as sql_func, or_
from sqlalchemy.orm import Session, joinedload

from .. import __version__ as app_version
from ..jinja_env import templates
from ..auth import SURGEON_ADMIN_PREVIEW_DEVICE_NAME, get_current_surgeon
from ..call_schedule_utils import (
    build_call_group_rows,
    build_call_rail_slots,
    build_merged_slot_index,
    index_rotations_by_group_date,
    serialize_call_group_rail,
)
from ..conflicts import check_conflicts
from ..database import get_db
from ..models import (
    Availability,
    CallGroup,
    CallRotation,
    ClinicSchedule,
    DayOff,
    Meeting,
    MeetingAttendee,
    PatientAssignment,
    Surgeon,
    SurgeonDayItem,
    SurgicalCase,
)

router = APIRouter(prefix="/surgeon")

def _base(request: Request, surgeon, device=None, **kwargs):
    desktop_preview = (
        device is not None
        and getattr(device, "device_name", None) == SURGEON_ADMIN_PREVIEW_DEVICE_NAME
    )
    return {
        "request": request,
        "surgeon": surgeon,
        "today": date.today(),
        "desktop_preview": desktop_preview,
        "app_version": app_version,
        **kwargs,
    }


def _session_times(session: str):
    if session == "am":
        return ("08:00", "12:00")
    if session == "pm":
        return ("13:00", "17:00")
    return ("08:00", "17:00")


def _open_surgical_location(loc) -> bool:
    if not loc:
        return False
    lt = (loc.location_type or "").lower()
    if lt == "hospital":
        return True
    name = (loc.name or "").lower()
    return "adventhealth" in name or "hospital" in name


def _serialize_off(s: Surgeon, viewer_id: int) -> dict:
    return {
        "initials": s.initials,
        "displayName": s.full_name,
        "isSelf": s.id == viewer_id,
    }


def _serialize_personal(pi: SurgeonDayItem) -> dict:
    return {
        "id": pi.id,
        "title": pi.title,
        "notes": (pi.notes or "").strip(),
        "start": pi.start_time.strftime("%H:%M") if pi.start_time else None,
        "end": pi.end_time.strftime("%H:%M") if pi.end_time else None,
        "sortOrder": pi.sort_order or 0,
    }


def _serialize_day(
    day,
    rotations,
    day_off,
    meetings,
    patients,
    clinics,
    surgeries,
    off_surgeons,
    personal_items,
    viewer_id: int,
    call_group_rail: list | None = None,
) -> dict:
    return {
        "date": day.isoformat(),
        "dayName": day.strftime("%A"),
        "dayShort": day.strftime("%a"),
        "dayNum": int(day.strftime("%-d")),
        "dayFull": day.strftime("%B %-d, %Y"),
        "rotations": [
            {"type": "oncall", "label": "On-Call"}
            for r in rotations
        ],
        "callGroupRail": call_group_rail or [],
        "dayOff": {"reason": day_off.reason or "Day Off"} if day_off else None,
        "meetings": [
            {
                "title": m.title,
                "start": m.start_time.strftime("%H:%M") if m.start_time else None,
                "end": m.end_time.strftime("%H:%M") if m.end_time else None,
                "location": m.location_text or "",
                "allDay": m.start_time is None,
            }
            for m in meetings
        ],
        "patients": {"count": patients.patient_count} if (patients and patients.patient_count > 0) else None,
        "clinics": [
            {
                "name": "OFF" if (cs.assignment_type or "assigned") == "off" else cs.location.name,
                "color": "#cbd5e1" if (cs.assignment_type or "assigned") == "off" else (cs.location.color or "#0ea5e9"),
                "session": cs.session,
                "start": _session_times(cs.session)[0],
                "end": _session_times(cs.session)[1],
                "assignmentType": cs.assignment_type or "assigned",
            }
            for cs in clinics
            if (cs.assignment_type or "assigned") == "off" or cs.location
        ],
        "surgeries": [
            {
                "id": sc.id,
                "start": sc.start_time.strftime("%H:%M") if sc.start_time else "08:00",
                "end": sc.end_time.strftime("%H:%M") if sc.end_time else None,
                "patientName": sc.patient_name or "",
                "procedure": sc.procedure or "",
                "room": (sc.location.name if sc.location else None) or sc.room_text or "",
                "status": sc.status or "scheduled",
                "surgeonNotes": sc.surgeon_notes or "",
                "color": (sc.location.color or None) if sc.location else None,
            }
            for sc in surgeries
        ],
        "offSurgeons": [_serialize_off(s, viewer_id) for s in off_surgeons],
        "personalItems": [_serialize_personal(p) for p in personal_items],
    }


def _build_off_surgeons_by_day(db: Session, week_start: date, week_end: date) -> dict:
    rows = (
        db.query(DayOff)
        .options(joinedload(DayOff.surgeon))
        .filter(
            DayOff.status == "approved",
            DayOff.start_date <= week_end,
            DayOff.end_date >= week_start,
        )
        .all()
    )
    by_day: dict = {}
    for off in rows:
        su = off.surgeon
        if not su or not su.is_active:
            continue
        span_start = max(off.start_date, week_start)
        span_end = min(off.end_date, week_end)
        d = span_start
        while d <= span_end:
            by_day.setdefault(d, {})[su.id] = su
            d += timedelta(days=1)
    return by_day


def _personal_by_day(db: Session, surgeon_id: int, week_start: date, week_end: date) -> dict:
    items = (
        db.query(SurgeonDayItem)
        .filter(
            SurgeonDayItem.surgeon_id == surgeon_id,
            SurgeonDayItem.date >= week_start,
            SurgeonDayItem.date <= week_end,
        )
        .order_by(SurgeonDayItem.date, SurgeonDayItem.sort_order, SurgeonDayItem.id)
        .all()
    )
    m = {}
    for it in items:
        m.setdefault(it.date, []).append(it)
    return m


def _meetings_for_surgeon_in_range(db: Session, surgeon_id: int, start_day: date, end_day: date) -> list[Meeting]:
    return (
        db.query(Meeting)
        .outerjoin(MeetingAttendee)
        .filter(
            Meeting.date >= start_day,
            Meeting.date <= end_day,
            or_(
                MeetingAttendee.surgeon_id == surgeon_id,
                ~Meeting.attendees.any(),
            ),
        )
        .distinct()
        .order_by(Meeting.date, Meeting.start_time, Meeting.id)
        .all()
    )


def _bucket_rows_by_day(rows, day_attr: str = "date") -> dict:
    grouped = {}
    for row in rows:
        grouped.setdefault(getattr(row, day_attr), []).append(row)
    return grouped


def _first_row_by_day(rows, day_attr: str = "date") -> dict:
    grouped = {}
    for row in rows:
        grouped.setdefault(getattr(row, day_attr), row)
    return grouped


def _compute_schedule_slots(ws: dict) -> dict:
    am, pm = [], []
    footer = []

    if ws["day_off"]:
        am.append({"text": "Day off", "neutral": True, "color": None, "hospital": False})

    for cs in ws["clinics"]:
        if (cs.assignment_type or "assigned") == "off":
            hosp = False
            entry = {
                "text": "OFF",
                "neutral": True,
                "color": "#cbd5e1",
                "hospital": False,
            }
            sess = (cs.session or "full").lower()
            if sess == "am":
                am.append(entry)
            elif sess == "pm":
                pm.append(entry)
            else:
                am.append({**entry, "text": "OFF · Full day"})
            continue

        loc = cs.location
        if not loc:
            continue
        hosp = _open_surgical_location(loc)
        sess = (cs.session or "full").lower()
        entry = {
            "text": loc.name,
            "neutral": False,
            "color": loc.color or "#0ea5e9",
            "hospital": hosp,
        }
        if sess == "am":
            am.append(entry)
        elif sess == "pm":
            pm.append(entry)
        else:
            am.append({**entry, "text": f"{loc.name} · Full day"})

    for m in ws["meetings"]:
        if m.start_time is None:
            footer.append({"kind": "meeting", "text": m.title})
            continue
        line = {"text": m.title, "neutral": True, "color": None, "hospital": False}
        if m.start_time.hour < 12:
            am.append(line)
        else:
            pm.append(line)

    if ws["patients"] and ws["patients"].patient_count > 0:
        n = ws["patients"].patient_count
        am.append({"text": f"{n} patients", "neutral": True, "color": None, "hospital": False})

    for sc in ws["surgeries"]:
        st = sc.start_time
        h = st.hour if st else 8
        label = (sc.patient_name or sc.procedure or "Surgery").strip() or "Surgery"
        if len(label) > 42:
            label = label[:39] + "…"
        col = (sc.location.color if sc.location else None) or None
        line = {
            "text": f"Surgery · {label}",
            "neutral": col is None,
            "color": col,
            "hospital": False,
        }
        if h < 12:
            am.append(line)
        else:
            pm.append(line)

    for p in ws.get("personal_items") or []:
        footer.append({"kind": "personal", "text": p.title, "id": p.id})

    return {"am": am, "pm": pm, "footer": footer}


@router.get("/register", response_class=HTMLResponse)
def register_page(request: Request, token: str = ""):
    return templates.TemplateResponse(
        "surgeon/register.html",
        {"request": request, "token": token, "app_version": app_version},
    )


@router.get("/schedule", response_class=HTMLResponse)
def schedule(request: Request, week_offset: int = 0, db: Session = Depends(get_db), auth=Depends(get_current_surgeon)):
    surgeon, device = auth
    today = date.today()
    week_start = today - timedelta(days=today.weekday()) + timedelta(weeks=week_offset)
    week_days = [week_start + timedelta(days=i) for i in range(7)]
    week_end = week_days[-1]
    summary_start = min(week_start, today)
    summary_end = max(week_end, today)

    call_groups = (
        db.query(CallGroup)
        .order_by(CallGroup.sort_order, CallGroup.name, CallGroup.id)
        .all()
    )
    call_group_rows = build_call_group_rows(call_groups)
    practice_rotations = (
        db.query(CallRotation)
        .options(
            joinedload(CallRotation.surgeon),
            joinedload(CallRotation.call_group),
        )
        .filter(
            CallRotation.date >= week_days[0],
            CallRotation.date <= week_end,
        )
        .all()
    )
    call_rotation_index = index_rotations_by_group_date(practice_rotations, call_groups)

    rotations_by_day = _bucket_rows_by_day(
        db.query(CallRotation)
        .filter(
            CallRotation.surgeon_id == surgeon.id,
            CallRotation.date >= summary_start,
            CallRotation.date <= summary_end,
        )
        .all()
    )
    patient_by_day = _first_row_by_day(
        db.query(PatientAssignment)
        .filter(
            PatientAssignment.surgeon_id == surgeon.id,
            PatientAssignment.date >= summary_start,
            PatientAssignment.date <= summary_end,
        )
        .order_by(PatientAssignment.date, PatientAssignment.id)
        .all()
    )
    meetings_by_day = _bucket_rows_by_day(
        _meetings_for_surgeon_in_range(db, surgeon.id, summary_start, summary_end)
    )
    clinics_by_day = _bucket_rows_by_day(
        db.query(ClinicSchedule)
        .options(joinedload(ClinicSchedule.location))
        .filter(
            ClinicSchedule.surgeon_id == surgeon.id,
            ClinicSchedule.date >= summary_start,
            ClinicSchedule.date <= summary_end,
        )
        .order_by(ClinicSchedule.date, ClinicSchedule.session, ClinicSchedule.id)
        .all()
    )
    surgeries_by_day = _bucket_rows_by_day(
        db.query(SurgicalCase)
        .options(joinedload(SurgicalCase.location))
        .filter(
            SurgicalCase.surgeon_id == surgeon.id,
            SurgicalCase.date >= summary_start,
            SurgicalCase.date <= summary_end,
            SurgicalCase.status != "cancelled",
        )
        .order_by(SurgicalCase.date, SurgicalCase.start_time, SurgicalCase.id)
        .all()
    )
    my_off_rows = (
        db.query(DayOff)
        .filter(
            DayOff.surgeon_id == surgeon.id,
            DayOff.start_date <= summary_end,
            DayOff.end_date >= summary_start,
            DayOff.status == "approved",
        )
        .order_by(DayOff.start_date, DayOff.id)
        .all()
    )
    my_off_by_day = {}
    for off in my_off_rows:
        span_start = max(off.start_date, summary_start)
        span_end = min(off.end_date, summary_end)
        d = span_start
        while d <= span_end:
            my_off_by_day.setdefault(d, off)
            d += timedelta(days=1)

    week_summary = []
    for day in week_days:
        week_summary.append({
            "date": day,
            "rotations": rotations_by_day.get(day, []),
            "day_off": my_off_by_day.get(day),
            "meetings": meetings_by_day.get(day, []),
            "patients": patient_by_day.get(day),
            "clinics": clinics_by_day.get(day, []),
            "surgeries": surgeries_by_day.get(day, []),
        })

    off_by_day = _build_off_surgeons_by_day(db, week_days[0], week_end)
    personal_by_day = _personal_by_day(db, surgeon.id, week_days[0], week_end)

    for ws in week_summary:
        d = ws["date"]
        off_map = off_by_day.get(d, {})
        ws["off_surgeons"] = sorted(
            off_map.values(),
            key=lambda s: ((s.last_name or "").lower(), (s.first_name or "").lower()),
        )
        ws["personal_items"] = personal_by_day.get(d, [])
        ws["slots"] = _compute_schedule_slots(ws)
        ws["call_rail_slots"] = build_call_rail_slots(call_group_rows, call_rotation_index, d)

    today_bucket = next((ws for ws in week_summary if ws["date"] == today), None)
    if not today_bucket:
        today_bucket = {
            "date": today,
            "rotations": rotations_by_day.get(today, []),
            "day_off": my_off_by_day.get(today),
            "meetings": meetings_by_day.get(today, []),
            "patients": patient_by_day.get(today),
            "clinics": clinics_by_day.get(today, []),
            "surgeries": surgeries_by_day.get(today, []),
        }
    today_summary = {
        "date": today,
        "rotations": today_bucket["rotations"],
        "day_off": today_bucket["day_off"],
        "meetings": today_bucket["meetings"],
        "patients": today_bucket["patients"],
        "clinics": today_bucket["clinics"],
        "surgeries": today_bucket["surgeries"],
    }

    week_json = _json.dumps([
        _serialize_day(
            ws["date"],
            ws["rotations"],
            ws["day_off"],
            ws["meetings"],
            ws["patients"],
            ws["clinics"],
            ws["surgeries"],
            ws["off_surgeons"],
            ws["personal_items"],
            surgeon.id,
            call_group_rail=serialize_call_group_rail(ws["call_rail_slots"]),
        )
        for ws in week_summary
    ])

    return templates.TemplateResponse(
        "surgeon/schedule.html",
        _base(
            request,
            surgeon,
            device=device,
            week_days=week_days,
            week_summary=week_summary,
            call_groups=call_groups,
            today_summary=today_summary,
            week_offset=week_offset,
            week_json=week_json,
        ),
    )


@router.get("/call-schedule", response_class=HTMLResponse)
def call_schedule_page(
    request: Request,
    week_offset: int = 0,
    schedule_view: str = "week",
    db: Session = Depends(get_db),
    auth=Depends(get_current_surgeon),
):
    surgeon, device = auth
    today = date.today()
    week_start = today - timedelta(days=today.weekday()) + timedelta(weeks=week_offset)
    use_30d = schedule_view == "30d"
    if use_30d:
        schedule_days = [week_start + timedelta(days=i) for i in range(30)]
    else:
        schedule_days = [week_start + timedelta(days=i) for i in range(7)]
    schedule_view = "30d" if use_30d else "week"

    call_groups = (
        db.query(CallGroup)
        .order_by(CallGroup.sort_order, CallGroup.name, CallGroup.id)
        .all()
    )
    call_group_rows = build_call_group_rows(call_groups)
    rotations = (
        db.query(CallRotation)
        .options(
            joinedload(CallRotation.surgeon),
            joinedload(CallRotation.call_group),
        )
        .filter(
            CallRotation.date >= schedule_days[0],
            CallRotation.date <= schedule_days[-1],
        )
        .all()
    )
    call_rotation_index = index_rotations_by_group_date(rotations, call_groups)
    merged_slot_index = build_merged_slot_index(call_group_rows, call_rotation_index)

    return templates.TemplateResponse(
        "surgeon/call_schedule.html",
        _base(
            request,
            surgeon,
            device=device,
            schedule_days=schedule_days,
            schedule_view=schedule_view,
            call_groups=call_groups,
            call_group_rows=call_group_rows,
            merged_slot_index=merged_slot_index,
            week_offset=week_offset,
        ),
    )


@router.get("/availability", response_class=HTMLResponse)
def availability_page(request: Request, db: Session = Depends(get_db), auth=Depends(get_current_surgeon)):
    surgeon, device = auth
    today = date.today()
    avail_records = db.query(Availability).filter(
        Availability.surgeon_id == surgeon.id,
        Availability.date >= today,
        Availability.date <= today + timedelta(days=28),
    ).order_by(Availability.date).all()
    avail_map = {a.date: a for a in avail_records}

    days = []
    for i in range(28):
        d = today + timedelta(days=i)
        rec = avail_map.get(d)
        days.append({
            "date": d,
            "is_available": rec.is_available if rec else True,
            "start_time": rec.start_time if rec else None,
            "end_time": rec.end_time if rec else None,
        })

    # Group into weeks of 7 for the template
    weeks = [days[i:i+7] for i in range(0, len(days), 7)]
    return templates.TemplateResponse("surgeon/availability.html", _base(request, surgeon, device=device, weeks=weeks))


@router.post("/availability/save")
async def save_availability(
    request: Request,
    db: Session = Depends(get_db),
    auth=Depends(get_current_surgeon),
):
    surgeon, _ = auth
    today = date.today()
    form = await request.form()

    def parse_time(s: str):
        if not s:
            return None
        try:
            parts = s.strip().split(":")
            return time_type(int(parts[0]), int(parts[1]))
        except Exception:
            return None

    conflict_warnings = []

    for i in range(28):
        d = today + timedelta(days=i)
        date_str = d.isoformat()
        is_avail = form.get(f"avail_{date_str}") == "1"
        start_t = parse_time(form.get(f"start_{date_str}", ""))
        end_t = parse_time(form.get(f"end_{date_str}", ""))

        if not is_avail:
            conflicts = check_conflicts(
                surgeon.id,
                d,
                d,
                db,
                target_entity={"type": "availability", "date": d},
            )
            for msg in conflicts:
                conflict_warnings.append(f"{d.strftime('%b %-d')}: {msg}")

        existing = db.query(Availability).filter(
            Availability.surgeon_id == surgeon.id,
            Availability.date == d,
        ).first()
        if existing:
            existing.is_available = is_avail
            existing.start_time = start_t
            existing.end_time = end_t
        else:
            db.add(
                Availability(
                    surgeon_id=surgeon.id,
                    date=d,
                    is_available=is_avail,
                    start_time=start_t,
                    end_time=end_t,
                )
            )

    db.commit()

    if conflict_warnings:
        warn = urllib.parse.quote(" · ".join(conflict_warnings[:5]))
        return RedirectResponse(f"/surgeon/availability?saved=1&warn={warn}", status_code=303)
    return RedirectResponse("/surgeon/availability?saved=1", status_code=303)


def _cg_short(name: str) -> str:
    """'Winter Garden / Apopka / Minneola Hospital' → 'WG', 'Altamonte Hospital' → 'ALT'"""
    part = name.split('/')[0].strip()
    stop = {'hospital', 'clinic', 'center', 'medical', 'the', 'of', 'and', 'at', 'surgery'}
    words = [w for w in part.split() if w.lower() not in stop]
    if len(words) >= 2:
        return ''.join(w[0].upper() for w in words[:3])
    return words[0][:3].upper() if words else name[:3].upper()


def _dominant_cg_id(surgeon_id: int, sd: date, ed: date, db: Session):
    """Return the call_group_id the surgeon is assigned to most during sd–ed."""
    row = (
        db.query(CallRotation.call_group_id, sql_func.count(CallRotation.id).label('cnt'))
        .filter(
            CallRotation.surgeon_id == surgeon_id,
            CallRotation.date >= sd,
            CallRotation.date <= ed,
            CallRotation.call_group_id.isnot(None),
        )
        .group_by(CallRotation.call_group_id)
        .order_by(sql_func.count(CallRotation.id).desc())
        .first()
    )
    return row[0] if row else None


def _year_months(all_reqs) -> list[tuple[int, int]]:
    """Rolling 12-month window from the current month, extended for future requests beyond it."""
    today = date.today()
    months = []
    year = today.year
    month = today.month
    for offset in range(12):
        y = year + ((month - 1 + offset) // 12)
        m = ((month - 1 + offset) % 12) + 1
        months.append((y, m))
    seen = {(y, m) for y, m in months}
    for req in all_reqs:
        ym = (req.start_date.year, req.start_date.month)
        if ym not in seen and ym >= months[0]:
            months.append(ym)
            seen.add(ym)
    months.sort()
    return months


@router.get("/request-off", response_class=HTMLResponse)
def request_off_page(request: Request, db: Session = Depends(get_db), auth=Depends(get_current_surgeon)):
    surgeon, device = auth
    today = date.today()
    months = _year_months([])
    window_start = date(months[0][0], months[0][1], 1)
    discovery_end = today + timedelta(days=730)

    # All non-denied requests for active surgeons within a bounded future window.
    all_requests = (
        db.query(DayOff)
        .join(Surgeon, DayOff.surgeon_id == Surgeon.id)
        .filter(
            DayOff.status != "denied",
            Surgeon.is_active == True,
            DayOff.start_date <= discovery_end,
            DayOff.end_date >= window_start,
        )
        .order_by(DayOff.start_date)
        .options(joinedload(DayOff.surgeon))
        .all()
    )

    months = _year_months(all_requests)
    first_year, first_month = months[0]
    last_year, last_month = months[-1]
    display_range_label = f"{_cal.month_abbr[first_month]} {first_year} - {_cal.month_abbr[last_month]} {last_year}"
    is_physician = surgeon.staff_type == "physician"

    if is_physician:
        call_groups = db.query(CallGroup).order_by(CallGroup.sort_order, CallGroup.name).all()

        ph_reqs = [r for r in all_requests if r.surgeon.staff_type == "physician"]
        by_section: dict = defaultdict(list)
        for req in ph_reqs:
            cg_id = _dominant_cg_id(req.surgeon_id, req.start_date, req.end_date, db)
            by_section[(req.start_date.year, req.start_date.month, cg_id)].append(req)

        sections = []
        for y, m in months:
            for g in call_groups:
                reqs = by_section.get((y, m, g.id), [])
                sections.append({
                    "header": f"{_cal.month_abbr[m].upper()} {_cg_short(g.name)}",
                    "requests": reqs,
                })
    else:
        pa_reqs = [r for r in all_requests if r.surgeon.staff_type != "physician"]
        by_month: dict = defaultdict(list)
        for req in pa_reqs:
            by_month[(req.start_date.year, req.start_date.month)].append(req)

        sections = []
        for y, m in months:
            sections.append({
                "header": _cal.month_abbr[m].upper(),
                "requests": by_month.get((y, m), []),
            })

    return templates.TemplateResponse(
        "surgeon/request_off.html",
        _base(
            request,
            surgeon,
            device=device,
            sections=sections,
            today=today,
            display_range_label=display_range_label,
        ),
    )


@router.post("/request-off")
def submit_request_off(
    start_date: str = Form(...),
    end_date: str = Form(...),
    reason: str = Form(""),
    notes: str = Form(""),
    db: Session = Depends(get_db),
    auth=Depends(get_current_surgeon),
):
    surgeon, _ = auth
    today = date.today()
    sd = date.fromisoformat(start_date)
    ed = date.fromisoformat(end_date)
    if sd < today or ed < today:
        warn = urllib.parse.quote("Days off can only be requested for today or later.")
        return RedirectResponse(f"/surgeon/request-off?open=1&warn={warn}", status_code=303)
    if ed < sd:
        warn = urllib.parse.quote("End date must be the same day or after the start date.")
        return RedirectResponse(f"/surgeon/request-off?open=1&warn={warn}", status_code=303)

    # Conflict check: on-call, existing overlapping requests
    conflict_msgs = check_conflicts(
        surgeon.id,
        sd,
        ed,
        db,
        target_entity={"type": "day_off", "start_date": sd, "end_date": ed},
    )

    # Check for overlapping approved/pending requests for this surgeon
    overlap = db.query(DayOff).filter(
        DayOff.surgeon_id == surgeon.id,
        DayOff.status.in_(["pending", "approved"]),
        DayOff.start_date <= ed,
        DayOff.end_date >= sd,
    ).first()
    if overlap:
        conflict_msgs.append(
            f"You already have a request for {overlap.start_date.strftime('%b %-d')}–{overlap.end_date.strftime('%b %-d')}"
        )

    warn_param = ""
    if conflict_msgs:
        warn_param = "&warn=" + urllib.parse.quote(" · ".join(conflict_msgs[:3]))

    d = DayOff(
        surgeon_id=surgeon.id,
        start_date=sd,
        end_date=ed,
        reason=reason,
        notes=notes,
        status="pending",
    )
    db.add(d)
    db.commit()
    return RedirectResponse(f"/surgeon/request-off?submitted=1{warn_param}", status_code=303)


@router.get("/patients", response_class=HTMLResponse)
def patients_page(request: Request, db: Session = Depends(get_db), auth=Depends(get_current_surgeon)):
    surgeon, device = auth
    today = date.today()
    today_assignment = db.query(PatientAssignment).filter(
        PatientAssignment.surgeon_id == surgeon.id,
        PatientAssignment.date == today,
    ).first()
    upcoming = db.query(PatientAssignment).filter(
        PatientAssignment.surgeon_id == surgeon.id,
        PatientAssignment.date > today,
        PatientAssignment.date <= today + timedelta(days=7),
    ).order_by(PatientAssignment.date).all()
    return templates.TemplateResponse(
        "surgeon/patients.html",
        _base(request, surgeon, device=device, today_assignment=today_assignment, upcoming=upcoming),
    )
