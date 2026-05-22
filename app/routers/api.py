"""JSON API endpoints — FullCalendar event feed, push subscription, health."""
import json
import re
from collections import defaultdict
from datetime import date, datetime, time, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import or_
from sqlalchemy.orm import Session, joinedload

from ..auth import get_current_admin, get_current_surgeon
from ..database import get_db
from ..models import (
    Availability, CallCoverage, CallGroup, CallRotation, ClinicSchedule, DayOff, Meeting, MeetingAttendee,
    NativePushToken, NativeScheduleAlert, PatientAssignment, PushSubscription, Surgeon, SurgeonDayItem, SurgeonDevice, SurgicalCase,
)
from ..push import VAPID_PUBLIC_KEY
from ..push import send_native_push_to_surgeon
from ..conflicts import check_conflicts

router = APIRouter(prefix="/api")

# Clinical Trust — calendar events that are not clinic/hospital placement (PALETTES: --bg-grouped, --text-2)
NEUTRAL_CAL_BG = "#F4F6F9"
NEUTRAL_CAL_TEXT = "#4A6080"


def _parse_iso_date_range(start: str, end: str) -> tuple[date, date]:
    try:
        return date.fromisoformat(start[:10]), date.fromisoformat(end[:10])
    except ValueError as exc:
        raise HTTPException(400, "Invalid date range") from exc


def _pastel_from_location_hex(loc_hex: str) -> str:
    h = (loc_hex or "").strip()
    if len(h) == 7 and h.startswith("#"):
        return h + "99"
    return "#7dd3fc99"


def _call_group_abbrev(name):
    """Short label for call group (e.g. 'Winter Garden / Apopka' -> 'WG')."""
    if not name:
        return "?"
    s = re.sub(r"\s*(/|–|-)\s*", " ", name).strip()
    words = [w for w in s.split() if len(w) >= 2 and w.lower() not in ("hospital", "and", "the")]
    if not words:
        return (s[:3] or "?").upper()
    return "".join(w[0] for w in words[:3]).upper()


def _location_abbrev(loc, location_type=None):
    """AH for hospital, CL for clinic; + short site name (e.g. AH-Cler, CL-Apk)."""
    if not loc or not getattr(loc, "name", None):
        return "AH" if location_type == "hospital" else "CL"
    name = (loc.name or "").strip()
    t = (location_type or getattr(loc, "location_type", None) or "clinic").lower()
    prefix = "AH" if t == "hospital" else "CL"
    name = re.sub(r"\s*(advent\s*health|hospital|clinic)\s*", " ", name, flags=re.I).strip()
    words = name.split()
    if not words:
        return prefix
    first = words[0][:4] if words[0] else ""
    return f"{prefix}-{first}" if first else prefix


def _meetings_for_surgeon(db: Session, surgeon_id: int, start_date: date, end_date: date) -> list[Meeting]:
    return (
        db.query(Meeting)
        .outerjoin(MeetingAttendee)
        .filter(
            Meeting.date >= start_date,
            Meeting.date <= end_date,
            or_(
                MeetingAttendee.surgeon_id == surgeon_id,
                ~Meeting.attendees.any(),
            ),
        )
        .distinct()
        .order_by(Meeting.date, Meeting.start_time, Meeting.id)
        .all()
    )


def _fmt_time(value: time | None) -> str | None:
    return value.strftime("%H:%M") if value else None


def _session_times(session: str | None) -> tuple[str, str]:
    if session == "am":
        return ("08:00", "12:00")
    if session == "pm":
        return ("13:00", "17:00")
    return ("08:00", "17:00")


def _date_label(d: date) -> dict:
    return {
        "date": d.isoformat(),
        "dayName": d.strftime("%A"),
        "dayShort": d.strftime("%a"),
        "dayFull": d.strftime("%m-%d-%Y"),
    }


def _native_surgeon_rank_key(surgeon: Surgeon | None) -> tuple:
    if not surgeon:
        return (2, 999999, "", "")
    is_physician = (surgeon.staff_type or "physician") == "physician"
    rank = surgeon.sort_order or 0
    return (
        0 if is_physician else 1,
        rank if is_physician and rank > 0 else 999999,
        (surgeon.last_name or "").lower(),
        (surgeon.first_name or "").lower(),
    )


def _serialize_day_off(row: DayOff) -> dict:
    segments = _day_off_segments(row)
    return {
        "id": row.id,
        "surgeonId": row.surgeon_id,
        "surgeonName": row.surgeon.full_name if row.surgeon else "",
        "surgeonInitials": row.surgeon.initials if row.surgeon else "",
        "surgeonSortOrder": row.surgeon.sort_order if row.surgeon else 0,
        "startDate": row.start_date.isoformat(),
        "endDate": row.end_date.isoformat(),
        "reason": row.reason or "",
        "notes": row.notes or "",
        "adminNote": row.admin_note or "",
        "status": row.status or "pending",
        "isFullDay": row.is_full_day if row.is_full_day is not None else True,
        "start": _fmt_time(row.start_time),
        "end": _fmt_time(row.end_time),
        "segments": segments,
    }


def _day_off_segments(row: DayOff) -> list[dict]:
    if row.segments:
        try:
            parsed = json.loads(row.segments)
            if isinstance(parsed, list):
                return parsed
        except json.JSONDecodeError:
            pass
    segments = []
    current = row.start_date
    while current <= row.end_date:
        segments.append({
            "date": current.isoformat(),
            "isFullDay": row.is_full_day if row.is_full_day is not None else True,
            "start": _fmt_time(row.start_time),
            "end": _fmt_time(row.end_time),
        })
        current += timedelta(days=1)
    return segments


def _segment_for_date(row: DayOff, d: date) -> dict | None:
    for segment in _day_off_segments(row):
        if segment.get("date") == d.isoformat():
            return segment
    return None


def _normalize_day_off_segments(sd: date, ed: date, is_full_day: bool, start: str | None, end: str | None, raw: list | None) -> list[dict]:
    by_date = {str(item.get("date")): item for item in raw or [] if isinstance(item, dict)}
    segments = []
    current = sd
    while current <= ed:
        item = by_date.get(current.isoformat(), {})
        full = item.get("isFullDay", is_full_day)
        start_value = None if full else (item.get("start") or start)
        end_value = None if full else (item.get("end") or end)
        segments.append({
            "date": current.isoformat(),
            "isFullDay": bool(full),
            "start": start_value,
            "end": end_value,
        })
        current += timedelta(days=1)
    return segments


def _validate_day_off_segments(segments: list[dict]) -> None:
    for segment in segments:
        if segment.get("isFullDay"):
            continue
        start_t = _parse_hhmm(str(segment.get("start") or ""))
        end_t = _parse_hhmm(str(segment.get("end") or ""))
        if not start_t or not end_t or end_t <= start_t:
            raise HTTPException(400, "Partial days need a valid start and end time.")


def _serialize_native_alert(row: NativeScheduleAlert) -> dict:
    try:
        payload = json.loads(row.payload or "{}")
    except json.JSONDecodeError:
        payload = {}
    return {
        "id": row.id,
        "title": row.title,
        "body": row.body,
        "kind": row.kind or "schedule",
        "payload": payload,
        "isRead": row.read_at is not None,
        "createdAt": row.created_at.isoformat() if row.created_at else "",
    }


def _active_coverage_for_rotation(rotation: CallRotation) -> CallCoverage | None:
    for coverage in rotation.coverages or []:
        if coverage.status == "active":
            return coverage
    return None


def _serialize_call_assignment(rotation: CallRotation, viewer_id: int) -> dict:
    coverage = _active_coverage_for_rotation(rotation)
    original = rotation.surgeon
    covering = coverage.covering_surgeon if coverage else None
    active_surgeon = covering or original
    return {
        "rotationId": rotation.id,
        "groupId": rotation.call_group_id,
        "group": rotation.call_group.name if rotation.call_group else "Call",
        "surgeon": active_surgeon.full_name if active_surgeon else "No call",
        "surgeonId": active_surgeon.id if active_surgeon else None,
        "initials": active_surgeon.initials if active_surgeon else "NC",
        "isSelf": bool(active_surgeon and active_surgeon.id == viewer_id),
        "originalSurgeon": original.full_name if original else "No call",
        "originalSurgeonId": original.id if original else None,
        "originalInitials": original.initials if original else "NC",
        "coveringSurgeon": covering.full_name if covering else None,
        "coveringSurgeonId": covering.id if covering else None,
        "coveringInitials": covering.initials if covering else None,
        "isCovered": coverage is not None,
        "coverageId": coverage.id if coverage else None,
    }


def _cg_short_label(name: str) -> str:
    part = (name or "").split("/")[0].strip()
    stop = {"hospital", "clinic", "center", "medical", "the", "of", "and", "at", "surgery"}
    words = [w for w in part.split() if w.lower() not in stop]
    if len(words) >= 2:
        return "".join(w[0].upper() for w in words[:3])
    return words[0][:3].upper() if words else (name or "?")[:3].upper()


def _dominant_call_group_id(db: Session, surgeon_id: int, sd: date, ed: date) -> int | None:
    from sqlalchemy import func as sql_func
    row = (
        db.query(CallRotation.call_group_id, sql_func.count(CallRotation.id).label("cnt"))
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


def _months_spanned(sd: date, ed: date) -> list[tuple[int, int]]:
    months = []
    cursor = date(sd.year, sd.month, 1)
    end_month = date(ed.year, ed.month, 1)
    while cursor <= end_month:
        months.append((cursor.year, cursor.month))
        year = cursor.year + (1 if cursor.month == 12 else 0)
        month = 1 if cursor.month == 12 else cursor.month + 1
        cursor = date(year, month, 1)
    return months


def _native_viewer_sees_physicians(viewer: Surgeon) -> bool:
    return (viewer.staff_type or "").lower() == "physician"


def _native_day_off_sections(db: Session, viewer: Surgeon) -> list[dict]:
    today = date.today()
    current_month = date(today.year, today.month, 1)
    window_start = current_month - timedelta(days=95)
    discovery_end = today + timedelta(days=730)
    rows = (
        db.query(DayOff)
        .join(Surgeon, DayOff.surgeon_id == Surgeon.id)
        .filter(
            DayOff.status != "denied",
            Surgeon.is_active == True,  # noqa: E712
            DayOff.start_date <= discovery_end,
            DayOff.end_date >= window_start,
        )
        .order_by(DayOff.start_date)
        .options(joinedload(DayOff.surgeon))
        .all()
    )
    months = []
    cursor = date(window_start.year, window_start.month, 1)
    for _ in range(16):
        months.append((cursor.year, cursor.month))
        year = cursor.year + (1 if cursor.month == 12 else 0)
        month = 1 if cursor.month == 12 else cursor.month + 1
        cursor = date(year, month, 1)
    for req in rows:
        ym = (req.start_date.year, req.start_date.month)
        if ym not in months and ym >= months[0]:
            months.append(ym)
    months.sort()

    if _native_viewer_sees_physicians(viewer):
        by_month: dict[tuple[int, int], list[DayOff]] = defaultdict(list)
        for req in [r for r in rows if r.surgeon and r.surgeon.staff_type == "physician"]:
            for ym in _months_spanned(req.start_date, req.end_date):
                by_month[ym].append(req)
        for requests in by_month.values():
            requests.sort(key=lambda req: (_native_surgeon_rank_key(req.surgeon), req.start_date, req.id))
        return [
            {
                "header": f"{date(y, m, 1).strftime('%b').upper()} SURGEONS",
                "isCurrentMonth": y == today.year and m == today.month,
                "requests": [_serialize_day_off(r) for r in by_month.get((y, m), [])],
            }
            for y, m in months
        ]

    by_month: dict[tuple[int, int], list[DayOff]] = defaultdict(list)
    for req in [r for r in rows if r.surgeon and r.surgeon.staff_type != "physician"]:
        for ym in _months_spanned(req.start_date, req.end_date):
            by_month[ym].append(req)
    for requests in by_month.values():
        requests.sort(key=lambda req: (_native_surgeon_rank_key(req.surgeon), req.start_date, req.id))
    return [
        {
            "header": f"{date(y, m, 1).strftime('%b').upper()} PAS",
            "isCurrentMonth": y == today.year and m == today.month,
            "requests": [_serialize_day_off(r) for r in by_month.get((y, m), [])],
        }
        for y, m in months
    ]


@router.get("/health")
def health():
    return {"status": "ok"}


@router.get("/vapid-public-key")
def vapid_key():
    return {"publicKey": VAPID_PUBLIC_KEY}


# ── FullCalendar event feed (admin) ──────────────────────────────────────────

@router.get("/events")
def get_events(
    start: str,
    end: str,
    db: Session = Depends(get_db),
    admin=Depends(get_current_admin),
):
    start_date, end_date = _parse_iso_date_range(start, end)

    events = []
    SORT_DAYOFF, SORT_NOCALL, SORT_CALL, SORT_CLINIC, SORT_MTG, SORT_SURG, SORT_PTS = 0, 1, 2, 3, 4, 5, 6

    # Days off (approved) — grouped by date, one event per day at top of cell
    daysoff = db.query(DayOff).filter(
        DayOff.start_date <= end_date,
        DayOff.end_date >= start_date,
        DayOff.status == "approved",
    ).all()
    by_date = defaultdict(list)
    for d in daysoff:
        s = d.surgeon
        day = max(d.start_date, start_date)
        last = min(d.end_date, end_date)
        while day <= last:
            by_date[day].append((s, d.reason))
            day += timedelta(days=1)
    for day, pairs in by_date.items():
        initials_list = []
        surgeon_ids = []
        names_for_modal = []
        for s, reason in pairs:
            try:
                initials_list.append(s.initials)
            except Exception:
                initials_list.append((s.first_name or "?")[0] + (s.last_name or "?")[0])
            surgeon_ids.append(s.id)
            names_for_modal.append(s.full_name)
        short = " ".join(initials_list) + " OFF"
        events.append({
            "id": f"off-{day.isoformat()}",
            "title": short,
            "start": day.isoformat(),
            "color": NEUTRAL_CAL_BG,
            "textColor": NEUTRAL_CAL_TEXT,
            "extendedProps": {
                "type": "dayoff",
                "surgeon_ids": surgeon_ids,
                "surgeon": ", ".join(names_for_modal),
                "reason": pairs[0][1] if pairs else None,
                "sort_key": SORT_DAYOFF,
            },
        })

    # Call rotations — by call group (not "On-Call"/"Backup")
    rotations = db.query(CallRotation).filter(
        CallRotation.date >= start_date,
        CallRotation.date <= end_date,
    ).all()
    for r in rotations:
        s = r.surgeon
        group = r.call_group
        group_name = group.name if group else ""
        group_abbrev = _call_group_abbrev(group_name) if group else "?"
        if not s:
            events.append({
                "id": f"rot-{r.id}",
                "title": f"{group_abbrev} NC",
                "start": r.date.isoformat(),
                "color": NEUTRAL_CAL_BG,
                "textColor": NEUTRAL_CAL_TEXT,
                "extendedProps": {"type": "oncall", "surgeon_id": None, "surgeon": "", "call_group": group_name, "role": "nc", "sort_key": SORT_NOCALL},
            })
            continue
        try:
            init = s.initials
        except Exception:
            init = ((s.first_name or "?")[0] + (s.last_name or "?")[0]).upper()
        short = f"{group_abbrev}: {init}"
        events.append({
            "id": f"rot-{r.id}",
            "title": short,
            "start": r.date.isoformat(),
            "color": NEUTRAL_CAL_BG,
            "textColor": NEUTRAL_CAL_TEXT,
            "extendedProps": {
                "type": "oncall",
                "surgeon": s.full_name,
                "surgeon_id": s.id,
                "call_group": group_name,
                "sort_key": SORT_CALL,
            },
        })

    # Meetings
    meetings = db.query(Meeting).filter(
        Meeting.date >= start_date,
        Meeting.date <= end_date,
    ).all()
    for m in meetings:
        start_dt = f"{m.date.isoformat()}T{m.start_time.isoformat()}" if m.start_time else m.date.isoformat()
        end_dt = f"{m.date.isoformat()}T{m.end_time.isoformat()}" if m.end_time else None
        short = (m.title[:12] + "…") if len(m.title or "") > 12 else (m.title or "MTG")
        events.append({
            "id": f"mtg-{m.id}",
            "title": f"MTG {short}",
            "start": start_dt,
            "end": end_dt,
            "color": NEUTRAL_CAL_BG,
            "textColor": NEUTRAL_CAL_TEXT,
            "extendedProps": {"type": "meeting", "location": m.location_text or "", "meeting_title": m.title or "", "sort_key": SORT_MTG},
        })

    # Patient assignments
    assignments = db.query(PatientAssignment).filter(
        PatientAssignment.date >= start_date,
        PatientAssignment.date <= end_date,
    ).all()
    for a in assignments:
        s = a.surgeon
        try:
            init = s.initials
        except Exception:
            init = ((s.first_name or "?")[0] + (s.last_name or "?")[0]).upper()
        short = f"{init} {a.patient_count}pts"
        events.append({
            "id": f"pt-{a.id}",
            "title": short,
            "start": f"{a.date.isoformat()}T09:00:00",
            "color": NEUTRAL_CAL_BG,
            "textColor": NEUTRAL_CAL_TEXT,
            "extendedProps": {"type": "patients", "surgeon": s.full_name, "surgeon_id": s.id, "count": a.patient_count, "sort_key": SORT_PTS},
        })

    # Clinic schedule
    clinic_schedules = db.query(ClinicSchedule).filter(
        ClinicSchedule.date >= start_date,
        ClinicSchedule.date <= end_date,
    ).all()
    for cs in clinic_schedules:
        s = cs.surgeon
        loc = cs.location
        try:
            init = s.initials
        except Exception:
            init = ((s.first_name or "?")[0] + (s.last_name or "?")[0]).upper()
        if (cs.assignment_type or "assigned") == "off":
            loc_abbrev = "OFF"
        else:
            loc_abbrev = _location_abbrev(loc) if loc else "CL"
        short = f"{init} {loc_abbrev}"
        time_slot = "T08:00:00" if cs.session == "am" else "T13:00:00" if cs.session == "pm" else "T08:00:00"
        loc_hex = "#cbd5e1" if (cs.assignment_type or "assigned") == "off" else (loc.color or "#0ea5e9").strip() if loc else "#0ea5e9"
        pastel_clinic = _pastel_from_location_hex(loc_hex)
        events.append({
            "id": f"clinic-{cs.id}",
            "title": short,
            "start": f"{cs.date.isoformat()}{time_slot}",
            "color": pastel_clinic,
            "textColor": "#1e293b",
            "extendedProps": {
                "type": "clinic",
                "surgeon": s.full_name,
                "surgeon_id": s.id,
                "location": "OFF" if (cs.assignment_type or "assigned") == "off" else (loc.name if loc else ""),
                "session": cs.session,
                "assignment_type": cs.assignment_type or "assigned",
                "notes": cs.notes or "",
                "sort_key": SORT_CLINIC,
            },
        })

    # Surgical cases
    surgeries = db.query(SurgicalCase).options(
        joinedload(SurgicalCase.location),
    ).filter(
        SurgicalCase.date >= start_date,
        SurgicalCase.date <= end_date,
        SurgicalCase.status != "cancelled",
    ).all()
    for c in surgeries:
        s = c.surgeon
        try:
            init = s.initials
        except Exception:
            init = ((s.first_name or "?")[0] + (s.last_name or "?")[0]).upper()
        short = f"{init} Sx"
        loc_name = c.location.name if c.location else (c.room_text or "OR")
        start_dt = f"{c.date.isoformat()}T{c.start_time.isoformat()}" if c.start_time else c.date.isoformat()
        end_dt = f"{c.date.isoformat()}T{c.end_time.isoformat()}" if c.end_time else None
        loc = c.location
        if loc and getattr(loc, "color", None):
            surg_hex = (loc.color or "").strip()
            surg_bg = _pastel_from_location_hex(surg_hex)
            surg_tc = "#1e293b"
        else:
            surg_bg = NEUTRAL_CAL_BG
            surg_tc = NEUTRAL_CAL_TEXT
        events.append({
            "id": f"surg-{c.id}",
            "title": short,
            "start": start_dt,
            "end": end_dt,
            "color": surg_bg,
            "textColor": surg_tc,
            "extendedProps": {
                "type": "surgery",
                "surgeon": s.full_name,
                "surgeon_id": s.id,
                "location": loc_name,
                "procedure": c.procedure,
                "patient_name": c.patient_name,
                "sort_key": SORT_SURG,
            },
        })

    # Unavailability (NC)
    unavails = db.query(Availability).filter(
        Availability.date >= start_date,
        Availability.date <= end_date,
        Availability.is_available == False,
    ).all()
    for av in unavails:
        s = av.surgeon
        try:
            init = s.initials
        except Exception:
            init = ((s.first_name or "?")[0] + (s.last_name or "?")[0]).upper()
        events.append({
            "id": f"unavail-{av.id}",
            "title": f"{init} NC",
            "start": av.date.isoformat(),
            "color": NEUTRAL_CAL_BG,
            "textColor": NEUTRAL_CAL_TEXT,
            "display": "background",
            "extendedProps": {"type": "unavailable", "surgeon": s.full_name, "surgeon_id": s.id, "sort_key": SORT_NOCALL},
        })

    return JSONResponse(events)


# ── Surgeon-scoped event feed ─────────────────────────────────────────────────

@router.get("/my-events")
def get_my_events(
    start: str,
    end: str,
    db: Session = Depends(get_db),
    auth=Depends(get_current_surgeon),
):
    surgeon, _ = auth
    start_date, end_date = _parse_iso_date_range(start, end)

    events = []

    rotations = db.query(CallRotation).filter(
        CallRotation.surgeon_id == surgeon.id,
        CallRotation.date >= start_date,
        CallRotation.date <= end_date,
    ).all()
    for r in rotations:
        label = "On-Call"
        events.append({
            "id": f"rot-{r.id}", "title": f"🔔 {label}",
            "start": r.date.isoformat(),
            "color": NEUTRAL_CAL_BG,
            "textColor": NEUTRAL_CAL_TEXT,
            "extendedProps": {"type": "oncall"},
        })

    daysoff = db.query(DayOff).filter(
        DayOff.surgeon_id == surgeon.id,
        DayOff.start_date <= end_date,
        DayOff.end_date >= start_date,
        DayOff.status == "approved",
    ).all()
    for d in daysoff:
        events.append({
            "id": f"off-{d.id}", "title": "🏖 Day Off",
            "start": d.start_date.isoformat(),
            "end": (d.end_date + timedelta(days=1)).isoformat(),
            "color": NEUTRAL_CAL_BG,
            "textColor": NEUTRAL_CAL_TEXT,
        })

    # Meetings this surgeon is attending, plus "all surgeons" meetings with no attendees.
    for m in _meetings_for_surgeon(db, surgeon.id, start_date, end_date):
        start_dt = f"{m.date.isoformat()}T{m.start_time.isoformat()}" if m.start_time else m.date.isoformat()
        events.append({
            "id": f"mtg-{m.id}", "title": f"📋 {m.title}",
            "start": start_dt,
            "end": f"{m.date.isoformat()}T{m.end_time.isoformat()}" if m.end_time else None,
            "color": NEUTRAL_CAL_BG,
            "textColor": NEUTRAL_CAL_TEXT,
        })

    assignments = db.query(PatientAssignment).filter(
        PatientAssignment.surgeon_id == surgeon.id,
        PatientAssignment.date >= start_date,
        PatientAssignment.date <= end_date,
    ).all()
    for a in assignments:
        events.append({
            "id": f"pt-{a.id}", "title": f"🏥 {a.patient_count} patients",
            "start": f"{a.date.isoformat()}T09:00:00",
            "color": NEUTRAL_CAL_BG,
            "textColor": NEUTRAL_CAL_TEXT,
        })

    # Clinic / hospital site assignments (location colors only)
    my_clinics = db.query(ClinicSchedule).options(
        joinedload(ClinicSchedule.location),
    ).filter(
        ClinicSchedule.surgeon_id == surgeon.id,
        ClinicSchedule.date >= start_date,
        ClinicSchedule.date <= end_date,
    ).all()
    for cs in my_clinics:
        loc = cs.location
        loc_hex = (loc.color or "#0ea5e9").strip() if loc else "#0ea5e9"
        time_slot = "T08:00:00" if cs.session == "am" else "T13:00:00" if cs.session == "pm" else "T08:00:00"
        loc_label = loc.name if loc else "Clinic"
        events.append({
            "id": f"clinic-{cs.id}",
            "title": f"📍 {loc_label}",
            "start": f"{cs.date.isoformat()}{time_slot}",
            "color": _pastel_from_location_hex(loc_hex),
            "textColor": "#1e293b",
            "extendedProps": {"type": "clinic", "location": loc_label, "session": cs.session},
        })

    return JSONResponse(events)


@router.get("/native/home")
def native_home(
    start: str,
    end: str,
    db: Session = Depends(get_db),
    auth=Depends(get_current_surgeon),
):
    surgeon, _ = auth
    start_date, end_date = _parse_iso_date_range(start, end)
    today = date.today()

    days = []
    current = start_date
    while current <= end_date:
        days.append({**_date_label(current), "items": [], "offSurgeons": [], "callAssignments": []})
        current += timedelta(days=1)
    by_date = {d["date"]: d for d in days}

    my_day_off_rows = db.query(DayOff).filter(
        DayOff.surgeon_id == surgeon.id,
        DayOff.start_date <= end_date,
        DayOff.end_date >= start_date,
        DayOff.status.in_(["pending", "approved"]),
    ).all()

    def blocked_by_my_day_off(item_date: date, start_t: str | None = None, end_t: str | None = None) -> bool:
        for off in my_day_off_rows:
            if off.start_date <= item_date <= off.end_date:
                segment = _segment_for_date(off, item_date)
                if segment and segment.get("isFullDay"):
                    return True
                seg_start = _parse_hhmm(segment.get("start")) if segment else off.start_time
                seg_end = _parse_hhmm(segment.get("end")) if segment else off.end_time
                if not seg_start or not seg_end:
                    return True
                if not start_t:
                    return True
                item_start = _parse_hhmm(start_t)
                item_end = _parse_hhmm(end_t) or item_start
                if item_start and item_end and item_start < seg_end and item_end > seg_start:
                    return True
        return False

    for r in db.query(CallRotation).options(
        joinedload(CallRotation.call_group),
        joinedload(CallRotation.coverages).joinedload(CallCoverage.covering_surgeon),
        joinedload(CallRotation.surgeon),
    ).filter(
        CallRotation.date >= start_date,
        CallRotation.date <= end_date,
    ).all():
        coverage = _active_coverage_for_rotation(r)
        if r.surgeon_id == surgeon.id or (coverage and coverage.covering_surgeon_id == surgeon.id):
            by_date[r.date.isoformat()]["items"].append({
                "id": f"rot-{r.id}",
                "rawId": r.id,
                "type": "oncall",
                "title": "On-Call Coverage" if coverage and coverage.covering_surgeon_id == surgeon.id else "On-Call",
                "subtitle": r.call_group.name if r.call_group else "",
                "allDay": True,
            })

    for d in my_day_off_rows:
        span = max(d.start_date, start_date)
        span_end = min(d.end_date, end_date)
        while span <= span_end:
            segment = _segment_for_date(d, span) or {}
            is_full = segment.get("isFullDay", d.is_full_day if d.is_full_day is not None else True)
            by_date[span.isoformat()]["items"].append({
                "id": f"off-{d.id}-{span.isoformat()}",
                "type": "dayoff",
                "title": "Day Off",
                "subtitle": f"{d.reason or ''}{' · pending' if d.status == 'pending' else ''}".strip(" ·"),
                "start": None if is_full else segment.get("start") or _fmt_time(d.start_time),
                "end": None if is_full else segment.get("end") or _fmt_time(d.end_time),
                "allDay": is_full,
            })
            span += timedelta(days=1)

    for m in _meetings_for_surgeon(db, surgeon.id, start_date, end_date):
        by_date[m.date.isoformat()]["items"].append({
            "id": f"mtg-{m.id}",
            "type": "meeting",
            "title": m.title,
            "subtitle": m.location_text or "",
            "start": _fmt_time(m.start_time),
            "end": _fmt_time(m.end_time),
            "notes": m.notes or "",
        })

    for a in db.query(PatientAssignment).options(joinedload(PatientAssignment.location)).filter(
        PatientAssignment.surgeon_id == surgeon.id,
        PatientAssignment.date >= start_date,
        PatientAssignment.date <= end_date,
    ).order_by(PatientAssignment.date).all():
        if a.patient_count > 0:
            by_date[a.date.isoformat()]["items"].append({
                "id": f"pt-{a.id}",
                "type": "patients",
                "title": f"{a.patient_count} patients",
                "subtitle": (a.location.name if a.location else "") or a.notes or "",
                "start": "09:00",
                "notes": a.notes or "",
            })

    for cs in db.query(ClinicSchedule).options(joinedload(ClinicSchedule.location)).filter(
        ClinicSchedule.surgeon_id == surgeon.id,
        ClinicSchedule.date >= start_date,
        ClinicSchedule.date <= end_date,
    ).order_by(ClinicSchedule.date, ClinicSchedule.session, ClinicSchedule.id).all():
        start_t, end_t = _session_times(cs.session)
        if blocked_by_my_day_off(cs.date, start_t, end_t):
            continue
        title = "OFF" if (cs.assignment_type or "assigned") == "off" else (cs.location.name if cs.location else "Clinic")
        by_date[cs.date.isoformat()]["items"].append({
            "id": f"clinic-{cs.id}",
            "type": "clinic",
            "title": title,
            "subtitle": (cs.session or "full").upper(),
            "start": start_t,
            "end": end_t,
            "color": "#cbd5e1" if title == "OFF" else ((cs.location.color if cs.location else None) or "#0ea5e9"),
            "notes": cs.notes or "",
        })

    for sc in db.query(SurgicalCase).options(joinedload(SurgicalCase.location)).filter(
        SurgicalCase.surgeon_id == surgeon.id,
        SurgicalCase.date >= start_date,
        SurgicalCase.date <= end_date,
        SurgicalCase.status != "cancelled",
    ).order_by(SurgicalCase.date, SurgicalCase.start_time, SurgicalCase.id).all():
        if blocked_by_my_day_off(sc.date, _fmt_time(sc.start_time), _fmt_time(sc.end_time)):
            continue
        by_date[sc.date.isoformat()]["items"].append({
            "id": f"surg-{sc.id}",
            "rawId": sc.id,
            "type": "surgery",
            "title": sc.patient_name or "Surgery",
            "subtitle": sc.procedure or "",
            "start": _fmt_time(sc.start_time) or "08:00",
            "end": _fmt_time(sc.end_time),
            "location": (sc.location.name if sc.location else "") or sc.room_text or "",
            "room": sc.room_text or "",
            "status": sc.status or "scheduled",
            "notes": sc.notes or "",
            "surgeonNotes": sc.surgeon_notes or "",
            "color": (sc.location.color if sc.location else None) or "#e0f2fe",
        })

    for pi in db.query(SurgeonDayItem).filter(
        SurgeonDayItem.surgeon_id == surgeon.id,
        SurgeonDayItem.date >= start_date,
        SurgeonDayItem.date <= end_date,
    ).order_by(SurgeonDayItem.date, SurgeonDayItem.sort_order, SurgeonDayItem.id).all():
        by_date[pi.date.isoformat()]["items"].append({
            "id": f"personal-{pi.id}",
            "rawId": pi.id,
            "type": "personal",
            "title": pi.title,
            "subtitle": pi.notes or "",
            "start": _fmt_time(pi.start_time),
            "end": _fmt_time(pi.end_time),
            "notes": pi.notes or "",
        })

    for day in days:
        day["items"].sort(key=lambda item: (item.get("start") or "99:99", item["type"], item["title"]))

    avail_records = db.query(Availability).filter(
        Availability.surgeon_id == surgeon.id,
        Availability.date >= today,
        Availability.date <= today + timedelta(days=27),
    ).order_by(Availability.date).all()
    avail_map = {a.date: a for a in avail_records}
    availability = []
    for i in range(28):
        d = today + timedelta(days=i)
        rec = avail_map.get(d)
        availability.append({
            **_date_label(d),
            "isAvailable": rec.is_available if rec else True,
            "start": _fmt_time(rec.start_time) if rec else None,
            "end": _fmt_time(rec.end_time) if rec else None,
        })

    requests = [
        _serialize_day_off(row)
        for row in db.query(DayOff).filter(
            DayOff.surgeon_id == surgeon.id,
            DayOff.end_date >= today - timedelta(days=30),
        ).order_by(DayOff.start_date.desc(), DayOff.id.desc()).limit(50).all()
    ]

    call_groups = db.query(CallGroup).order_by(CallGroup.sort_order, CallGroup.name, CallGroup.id).all()
    rotations = db.query(CallRotation).options(
        joinedload(CallRotation.surgeon),
        joinedload(CallRotation.call_group),
        joinedload(CallRotation.coverages).joinedload(CallCoverage.covering_surgeon),
    ).filter(
        CallRotation.date >= start_date,
        CallRotation.date <= end_date,
    ).order_by(CallRotation.date, CallRotation.call_group_id, CallRotation.id).all()
    call_by_date: dict[str, list[dict]] = defaultdict(list)
    for r in rotations:
        assignment = _serialize_call_assignment(r, surgeon.id)
        call_by_date[r.date.isoformat()].append(assignment)
        if r.date.isoformat() in by_date:
            by_date[r.date.isoformat()]["callAssignments"].append(assignment)

    off_rows = db.query(DayOff).options(joinedload(DayOff.surgeon)).filter(
        DayOff.status == "approved",
        DayOff.start_date <= end_date,
        DayOff.end_date >= start_date,
    ).all()
    for off in off_rows:
        if not off.surgeon or not off.surgeon.is_active:
            continue
        span = max(off.start_date, start_date)
        span_end = min(off.end_date, end_date)
        while span <= span_end:
            if span.isoformat() in by_date:
                by_date[span.isoformat()]["offSurgeons"].append({
                    "initials": off.surgeon.initials,
                    "displayName": off.surgeon.full_name,
                    "isSelf": off.surgeon_id == surgeon.id,
                    "sortOrder": off.surgeon.sort_order or 0,
                    "staffType": off.surgeon.staff_type or "",
                })
            span += timedelta(days=1)

    for day in days:
        day["offSurgeons"].sort(key=lambda row: (
            0 if row.get("staffType") == "physician" else 1,
            row.get("sortOrder") or 999999,
            row["initials"],
        ))
    call_schedule = [
        {**_date_label(start_date + timedelta(days=i)), "assignments": call_by_date.get((start_date + timedelta(days=i)).isoformat(), [])}
        for i in range((end_date - start_date).days + 1)
    ]

    today_assignment = db.query(PatientAssignment).options(joinedload(PatientAssignment.location)).filter(
        PatientAssignment.surgeon_id == surgeon.id,
        PatientAssignment.date == today,
    ).first()
    upcoming_patients = db.query(PatientAssignment).options(joinedload(PatientAssignment.location)).filter(
        PatientAssignment.surgeon_id == surgeon.id,
        PatientAssignment.date > today,
        PatientAssignment.date <= today + timedelta(days=7),
    ).order_by(PatientAssignment.date).all()
    unread_alert_count = db.query(NativeScheduleAlert).filter(
        NativeScheduleAlert.surgeon_id == surgeon.id,
        NativeScheduleAlert.read_at.is_(None),
    ).count()
    recent_alerts = db.query(NativeScheduleAlert).filter(
        NativeScheduleAlert.surgeon_id == surgeon.id,
    ).order_by(NativeScheduleAlert.created_at.desc(), NativeScheduleAlert.id.desc()).limit(20).all()

    return {
        "surgeon": {"id": surgeon.id, "name": surgeon.full_name, "staffType": surgeon.staff_type},
        "range": {"start": start_date.isoformat(), "end": end_date.isoformat()},
        "days": days,
        "availability": availability,
        "requests": requests,
        "dayOffSections": _native_day_off_sections(db, surgeon),
        "callGroups": [{"id": g.id, "name": g.name} for g in call_groups],
        "surgeons": [
            {"id": s.id, "name": s.full_name, "initials": s.initials, "staffType": s.staff_type, "sortOrder": s.sort_order or 0}
            for s in sorted(
                db.query(Surgeon).filter(Surgeon.is_active == True).all(),  # noqa: E712
                key=_native_surgeon_rank_key,
            )
        ],
        "callSchedule": call_schedule,
        "alerts": {
            "unreadCount": unread_alert_count,
            "recent": [_serialize_native_alert(row) for row in recent_alerts],
        },
        "patients": {
            "today": {
                "date": today.isoformat(),
                "count": today_assignment.patient_count if today_assignment else 0,
                "notes": today_assignment.notes if today_assignment else "",
                "location": today_assignment.location.name if today_assignment and today_assignment.location else "",
            },
            "upcoming": [
                {
                    "date": row.date.isoformat(),
                    "count": row.patient_count,
                    "notes": row.notes or "",
                    "location": row.location.name if row.location else "",
                }
                for row in upcoming_patients
            ],
        },
    }


@router.post("/native/alerts/read")
def native_mark_alerts_read(
    db: Session = Depends(get_db),
    auth=Depends(get_current_surgeon),
):
    surgeon, _ = auth
    rows = db.query(NativeScheduleAlert).filter(
        NativeScheduleAlert.surgeon_id == surgeon.id,
        NativeScheduleAlert.read_at.is_(None),
    ).all()
    now = datetime.utcnow()
    for row in rows:
        row.read_at = now
    db.commit()
    return {"ok": True, "count": len(rows)}


class NativeRequestOffBody(BaseModel):
    start_date: date
    end_date: date
    reason: str = ""
    notes: str = ""
    is_full_day: bool = True
    start: str | None = None
    end: str | None = None
    segments: list[dict] | None = None


@router.post("/native/request-off")
def native_request_off(
    body: NativeRequestOffBody,
    db: Session = Depends(get_db),
    auth=Depends(get_current_surgeon),
):
    surgeon, _ = auth
    today = date.today()
    if body.start_date < today or body.end_date < today:
        raise HTTPException(400, "Days off can only be requested for today or later.")
    if body.end_date < body.start_date:
        raise HTTPException(400, "End date must be the same day or after the start date.")

    segments = _normalize_day_off_segments(body.start_date, body.end_date, body.is_full_day, body.start, body.end, body.segments)
    _validate_day_off_segments(segments)
    first_partial = next((s for s in segments if not s.get("isFullDay")), None)
    start_t = _parse_hhmm(first_partial.get("start")) if first_partial else None
    end_t = _parse_hhmm(first_partial.get("end")) if first_partial else None

    conflict_msgs = check_conflicts(
        surgeon.id,
        body.start_date,
        body.end_date,
        db,
        target_entity={"type": "day_off", "start_date": body.start_date, "end_date": body.end_date},
    )
    overlap = db.query(DayOff).filter(
        DayOff.surgeon_id == surgeon.id,
        DayOff.status.in_(["pending", "approved"]),
        DayOff.start_date <= body.end_date,
        DayOff.end_date >= body.start_date,
    ).first()
    if overlap:
        conflict_msgs.append(
            f"You already have a request for {overlap.start_date.isoformat()} - {overlap.end_date.isoformat()}"
        )
    if conflict_msgs:
        return {"ok": False, "request": None, "warnings": conflict_msgs[:5]}

    row = DayOff(
        surgeon_id=surgeon.id,
        start_date=body.start_date,
        end_date=body.end_date,
        reason=body.reason.strip(),
        notes=body.notes.strip(),
        is_full_day=body.is_full_day,
        start_time=start_t,
        end_time=end_t,
        segments=json.dumps(segments),
        status="pending",
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    send_native_push_to_surgeon(
        surgeon.id,
        "Days off request pending",
        f"{body.start_date.strftime('%b %-d')} request sent for approval",
        db,
        {"type": "day_off", "requestId": row.id},
    )
    return {"ok": True, "request": _serialize_day_off(row), "warnings": conflict_msgs[:3]}


@router.put("/native/request-off/{dayoff_id}")
def native_update_request_off(
    dayoff_id: int,
    body: NativeRequestOffBody,
    db: Session = Depends(get_db),
    auth=Depends(get_current_surgeon),
):
    surgeon, _ = auth
    row = db.get(DayOff, dayoff_id)
    if not row or row.surgeon_id != surgeon.id:
        raise HTTPException(404, "Days off request not found")
    today = date.today()
    if body.start_date < today or body.end_date < today:
        raise HTTPException(400, "Days off can only be changed for today or later.")
    if body.end_date < body.start_date:
        raise HTTPException(400, "End date must be the same day or after the start date.")

    segments = _normalize_day_off_segments(body.start_date, body.end_date, body.is_full_day, body.start, body.end, body.segments)
    _validate_day_off_segments(segments)
    first_partial = next((s for s in segments if not s.get("isFullDay")), None)
    start_t = _parse_hhmm(first_partial.get("start")) if first_partial else None
    end_t = _parse_hhmm(first_partial.get("end")) if first_partial else None

    conflict_msgs = check_conflicts(
        surgeon.id,
        body.start_date,
        body.end_date,
        db,
        exclude_dayoff_id=row.id,
        target_entity={"type": "day_off", "start_date": body.start_date, "end_date": body.end_date},
    )
    overlap = db.query(DayOff).filter(
        DayOff.id != row.id,
        DayOff.surgeon_id == surgeon.id,
        DayOff.status.in_(["pending", "approved"]),
        DayOff.start_date <= body.end_date,
        DayOff.end_date >= body.start_date,
    ).first()
    if overlap:
        conflict_msgs.append(
            f"You already have a request for {overlap.start_date.isoformat()} - {overlap.end_date.isoformat()}"
        )
    if conflict_msgs:
        return {"ok": False, "request": _serialize_day_off(row), "warnings": conflict_msgs[:5]}

    row.start_date = body.start_date
    row.end_date = body.end_date
    row.reason = body.reason.strip()
    row.notes = body.notes.strip()
    row.is_full_day = body.is_full_day
    row.start_time = start_t
    row.end_time = end_t
    row.segments = json.dumps(segments)
    row.status = "pending"
    row.admin_note = None
    db.commit()
    db.refresh(row)
    send_native_push_to_surgeon(
        surgeon.id,
        "Days off request updated",
        f"{body.start_date.strftime('%b %-d')} request updated and pending approval",
        db,
        {"type": "day_off", "requestId": row.id},
    )
    return {"ok": True, "request": _serialize_day_off(row), "warnings": []}


@router.delete("/native/request-off/{dayoff_id}")
def native_cancel_request_off(
    dayoff_id: int,
    db: Session = Depends(get_db),
    auth=Depends(get_current_surgeon),
):
    surgeon, _ = auth
    row = db.get(DayOff, dayoff_id)
    if not row or row.surgeon_id != surgeon.id:
        raise HTTPException(404, "Days off request not found")
    db.delete(row)
    db.commit()
    send_native_push_to_surgeon(
        surgeon.id,
        "Days off canceled",
        "Your schedule has been restored for the canceled days.",
        db,
        {"type": "day_off", "requestId": dayoff_id, "status": "canceled"},
    )
    return {"ok": True}


class NativeCallCoverageBody(BaseModel):
    rotation_id: int
    covering_surgeon_id: int | None = None
    notes: str = ""


@router.post("/native/call-coverage")
def native_call_coverage(
    body: NativeCallCoverageBody,
    db: Session = Depends(get_db),
    auth=Depends(get_current_surgeon),
):
    surgeon, _ = auth
    rotation = db.query(CallRotation).options(joinedload(CallRotation.surgeon), joinedload(CallRotation.call_group)).get(body.rotation_id)
    if not rotation:
        raise HTTPException(404, "Call assignment not found")
    covering_id = body.covering_surgeon_id or surgeon.id
    covering = db.get(Surgeon, covering_id)
    if not covering or not covering.is_active:
        raise HTTPException(400, "Covering surgeon is not active")
    original_staff_type = rotation.surgeon.staff_type if rotation.surgeon else surgeon.staff_type
    if covering.staff_type != original_staff_type:
        role = "surgeon" if original_staff_type == "physician" else "PA/staff"
        raise HTTPException(400, f"Coverage must be assigned to another {role}.")

    existing = db.query(CallCoverage).filter(
        CallCoverage.call_rotation_id == rotation.id,
        CallCoverage.status == "active",
    ).first()
    if existing:
        existing.status = "canceled"
        existing.canceled_at = datetime.utcnow()

    coverage = CallCoverage(
        call_rotation_id=rotation.id,
        original_surgeon_id=rotation.surgeon_id,
        covering_surgeon_id=covering.id,
        requested_by_surgeon_id=surgeon.id,
        notes=body.notes.strip() or None,
        status="active",
    )
    db.add(coverage)
    db.commit()
    db.refresh(coverage)
    if rotation.surgeon_id:
        send_native_push_to_surgeon(
            rotation.surgeon_id,
            "On-call coverage updated",
            f"{covering.initials} is covering {rotation.date.strftime('%b %-d')}",
            db,
            {"type": "call_coverage", "rotationId": rotation.id},
        )
    send_native_push_to_surgeon(
        covering.id,
        "On-call coverage assigned",
        f"You are covering {rotation.call_group.name if rotation.call_group else 'call'} on {rotation.date.strftime('%b %-d')}",
        db,
        {"type": "call_coverage", "rotationId": rotation.id},
    )
    rotation = db.query(CallRotation).options(
        joinedload(CallRotation.surgeon),
        joinedload(CallRotation.call_group),
        joinedload(CallRotation.coverages).joinedload(CallCoverage.covering_surgeon),
    ).get(rotation.id)
    return {"ok": True, "assignment": _serialize_call_assignment(rotation, surgeon.id)}


@router.post("/native/call-coverage/{coverage_id:int}/cancel")
def native_cancel_call_coverage(
    coverage_id: int,
    db: Session = Depends(get_db),
    auth=Depends(get_current_surgeon),
):
    surgeon, _ = auth
    coverage = db.get(CallCoverage, coverage_id)
    if not coverage or coverage.status != "active":
        raise HTTPException(404, "Coverage not found")
    coverage.status = "canceled"
    coverage.canceled_at = datetime.utcnow()
    db.commit()
    rotation = db.query(CallRotation).options(
        joinedload(CallRotation.surgeon),
        joinedload(CallRotation.call_group),
        joinedload(CallRotation.coverages).joinedload(CallCoverage.covering_surgeon),
    ).get(coverage.call_rotation_id)
    return {"ok": True, "assignment": _serialize_call_assignment(rotation, surgeon.id)}


class NativeAvailabilityRow(BaseModel):
    date: date
    isAvailable: bool
    start: str | None = None
    end: str | None = None


class NativeAvailabilityBody(BaseModel):
    days: list[NativeAvailabilityRow]


def _parse_hhmm(raw: str | None) -> time | None:
    if not raw:
        return None
    try:
        hour, minute = raw.split(":")[:2]
        return time(int(hour), int(minute))
    except Exception:
        return None


@router.post("/native/availability")
def native_save_availability(
    body: NativeAvailabilityBody,
    db: Session = Depends(get_db),
    auth=Depends(get_current_surgeon),
):
    surgeon, _ = auth
    warnings = []
    for row in body.days:
        existing = db.query(Availability).filter(
            Availability.surgeon_id == surgeon.id,
            Availability.date == row.date,
        ).first()
        if not row.isAvailable:
            warnings.extend(check_conflicts(
                surgeon.id,
                row.date,
                row.date,
                db,
                target_entity={"type": "availability", "date": row.date},
            ))
        if existing:
            existing.is_available = row.isAvailable
            existing.start_time = _parse_hhmm(row.start)
            existing.end_time = _parse_hhmm(row.end)
        else:
            db.add(Availability(
                surgeon_id=surgeon.id,
                date=row.date,
                is_available=row.isAvailable,
                start_time=_parse_hhmm(row.start),
                end_time=_parse_hhmm(row.end),
            ))
    db.commit()
    return {"ok": True, "warnings": warnings[:5]}


class NativeSurgeryNotesBody(BaseModel):
    notes: str = ""


@router.post("/native/surgical-case/{case_id:int}/notes")
def native_save_surgery_notes(
    case_id: int,
    body: NativeSurgeryNotesBody,
    db: Session = Depends(get_db),
    auth=Depends(get_current_surgeon),
):
    surgeon, _ = auth
    row = db.get(SurgicalCase, case_id)
    if not row or row.surgeon_id != surgeon.id:
        raise HTTPException(404, "Case not found")
    row.surgeon_notes = body.notes.strip() or None
    db.commit()
    send_native_push_to_surgeon(
        surgeon.id,
        "Surgical case notes updated",
        f"{row.date.strftime('%b %-d')} case notes saved",
        db,
        {"type": "surgical_case", "caseId": row.id},
    )
    return {"ok": True}


class NativePushTokenBody(BaseModel):
    token: str
    platform: str = "ios"


@router.post("/native/push-token")
def native_push_token(
    body: NativePushTokenBody,
    db: Session = Depends(get_db),
    auth=Depends(get_current_surgeon),
):
    surgeon, device = auth
    token = body.token.strip()
    if not token:
        raise HTTPException(400, "Push token is required")
    row = db.query(NativePushToken).filter(NativePushToken.token == token).first()
    if row:
        row.surgeon_id = surgeon.id
        row.device_id = device.id if device else None
        row.platform = body.platform or "ios"
        row.is_active = True
        row.updated_at = datetime.utcnow()
    else:
        db.add(NativePushToken(
            surgeon_id=surgeon.id,
            device_id=device.id if device else None,
            token=token,
            platform=body.platform or "ios",
            is_active=True,
        ))
    db.commit()
    return {"ok": True}


# ── Push subscription ─────────────────────────────────────────────────────────

@router.post("/push/subscribe")
async def subscribe_push(
    request: Request,
    db: Session = Depends(get_db),
    auth=Depends(get_current_surgeon),
):
    surgeon, device = auth
    body = await request.json()
    endpoint = body.get("endpoint")
    keys = body.get("keys", {})

    if not endpoint:
        raise HTTPException(400, "Missing endpoint")

    # Upsert subscription
    existing = db.query(PushSubscription).filter(
        PushSubscription.endpoint == endpoint
    ).first()
    if not existing:
        sub = PushSubscription(
            surgeon_id=surgeon.id,
            device_id=device.id,
            endpoint=endpoint,
            p256dh=keys.get("p256dh", ""),
            auth_key=keys.get("auth", ""),
        )
        db.add(sub)
        db.commit()
    return {"ok": True}
