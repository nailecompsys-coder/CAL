"""Calendar JSON API feeds."""
import re
from collections import defaultdict
from datetime import timedelta

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session, joinedload

from ..auth import get_current_admin, get_current_surgeon
from ..database import get_db
from ..models import (
    Availability, CallRotation, ClinicSchedule, DayOff, Meeting, SurgicalCase,
)
from ..native_support import meetings_for_surgeon as _meetings_for_surgeon
from .api_common import parse_iso_date_range

router = APIRouter(prefix="/api")

NEUTRAL_CAL_BG = "#F4F6F9"
NEUTRAL_CAL_TEXT = "#4A6080"


def _pastel_from_location_hex(loc_hex: str) -> str:
    h = (loc_hex or "").strip()
    if len(h) == 7 and h.startswith("#"):
        return h + "99"
    return "#7dd3fc99"


def _call_group_abbrev(name):
    """Short label for call group (e.g. 'Winter Garden / Apopka' -> 'WG')."""
    if not name:
        return "?"
    s = re.sub(r"\s*(/|-)\s*", " ", name).strip()
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


@router.get("/events")
def get_events(
    start: str,
    end: str,
    db: Session = Depends(get_db),
    admin=Depends(get_current_admin),
):
    start_date, end_date = parse_iso_date_range(start, end)

    events = []
    SORT_DAYOFF, SORT_NOCALL, SORT_CALL, SORT_CLINIC, SORT_MTG, SORT_SURG = 0, 1, 2, 3, 4, 5

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


@router.get("/my-events")
def get_my_events(
    start: str,
    end: str,
    db: Session = Depends(get_db),
    auth=Depends(get_current_surgeon),
):
    surgeon, _ = auth
    start_date, end_date = parse_iso_date_range(start, end)

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

    for m in _meetings_for_surgeon(db, surgeon.id, start_date, end_date):
        start_dt = f"{m.date.isoformat()}T{m.start_time.isoformat()}" if m.start_time else m.date.isoformat()
        events.append({
            "id": f"mtg-{m.id}", "title": f"📋 {m.title}",
            "start": start_dt,
            "end": f"{m.date.isoformat()}T{m.end_time.isoformat()}" if m.end_time else None,
            "color": NEUTRAL_CAL_BG,
            "textColor": NEUTRAL_CAL_TEXT,
        })

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
