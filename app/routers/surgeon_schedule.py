"""Surgeon schedule page routes."""
import json as _json
from datetime import date, timedelta

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import or_
from sqlalchemy.orm import Session, joinedload

from ..auth import get_current_surgeon
from ..call_schedule_utils import (
    build_call_group_rows,
    build_call_rail_slots,
    index_rotations_by_group_date,
    serialize_call_group_rail,
)
from ..database import get_db
from ..jinja_env import templates
from ..models import (
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
from .surgeon import _base, _serialize_personal

router = APIRouter(prefix="/surgeon")


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
                am.append({**entry, "text": "OFF - Full day"})
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
            am.append({**entry, "text": f"{loc.name} - Full day"})

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
            label = label[:39] + "..."
        col = (sc.location.color if sc.location else None) or None
        line = {
            "text": f"Surgery - {label}",
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
