"""Calendar API event builders."""

import re
from collections import defaultdict
from datetime import timedelta

from sqlalchemy.orm import Session, joinedload

from .models import Availability, CallRotation, ClinicSchedule, DayOff, Meeting, SurgicalCase
from .native_support import meetings_for_surgeon

NEUTRAL_CAL_BG = "#F4F6F9"
NEUTRAL_CAL_TEXT = "#4A6080"

SORT_DAYOFF, SORT_NOCALL, SORT_CALL, SORT_CLINIC, SORT_MTG, SORT_SURG = 0, 1, 2, 3, 4, 5


def pastel_from_location_hex(loc_hex: str) -> str:
    h = (loc_hex or "").strip()
    if len(h) == 7 and h.startswith("#"):
        return h + "99"
    return "#7dd3fc99"


def call_group_abbrev(name):
    """Short label for call group (e.g. 'Winter Garden / Apopka' -> 'WG')."""
    if not name:
        return "?"
    s = re.sub(r"\s*(/|-)\s*", " ", name).strip()
    words = [w for w in s.split() if len(w) >= 2 and w.lower() not in ("hospital", "and", "the")]
    if not words:
        return (s[:3] or "?").upper()
    return "".join(w[0] for w in words[:3]).upper()


def location_abbrev(loc, location_type=None):
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


def surgeon_initials(surgeon) -> str:
    try:
        return surgeon.initials
    except Exception:
        return ((surgeon.first_name or "?")[0] + (surgeon.last_name or "?")[0]).upper()


def add_day_off_events(events: list[dict], db: Session, start_date, end_date) -> None:
    daysoff = db.query(DayOff).filter(
        DayOff.start_date <= end_date,
        DayOff.end_date >= start_date,
        DayOff.status == "approved",
    ).all()
    by_date = defaultdict(list)
    for day_off in daysoff:
        surgeon = day_off.surgeon
        day = max(day_off.start_date, start_date)
        last = min(day_off.end_date, end_date)
        while day <= last:
            by_date[day].append((surgeon, day_off.reason))
            day += timedelta(days=1)
    for day, pairs in by_date.items():
        initials_list = []
        surgeon_ids = []
        names_for_modal = []
        for surgeon, reason in pairs:
            initials_list.append(surgeon_initials(surgeon))
            surgeon_ids.append(surgeon.id)
            names_for_modal.append(surgeon.full_name)
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


def add_call_rotation_events(events: list[dict], db: Session, start_date, end_date) -> None:
    rotations = db.query(CallRotation).filter(
        CallRotation.date >= start_date,
        CallRotation.date <= end_date,
    ).all()
    for rotation in rotations:
        surgeon = rotation.surgeon
        group = rotation.call_group
        group_name = group.name if group else ""
        group_abbrev = call_group_abbrev(group_name) if group else "?"
        if not surgeon:
            events.append({
                "id": f"rot-{rotation.id}",
                "title": f"{group_abbrev} NC",
                "start": rotation.date.isoformat(),
                "color": NEUTRAL_CAL_BG,
                "textColor": NEUTRAL_CAL_TEXT,
                "extendedProps": {"type": "oncall", "surgeon_id": None, "surgeon": "", "call_group": group_name, "role": "nc", "sort_key": SORT_NOCALL},
            })
            continue
        short = f"{group_abbrev}: {surgeon_initials(surgeon)}"
        events.append({
            "id": f"rot-{rotation.id}",
            "title": short,
            "start": rotation.date.isoformat(),
            "color": NEUTRAL_CAL_BG,
            "textColor": NEUTRAL_CAL_TEXT,
            "extendedProps": {
                "type": "oncall",
                "surgeon": surgeon.full_name,
                "surgeon_id": surgeon.id,
                "call_group": group_name,
                "sort_key": SORT_CALL,
            },
        })


def add_meeting_events(events: list[dict], db: Session, start_date, end_date) -> None:
    meetings = db.query(Meeting).filter(
        Meeting.date >= start_date,
        Meeting.date <= end_date,
    ).all()
    for meeting in meetings:
        start_dt = f"{meeting.date.isoformat()}T{meeting.start_time.isoformat()}" if meeting.start_time else meeting.date.isoformat()
        end_dt = f"{meeting.date.isoformat()}T{meeting.end_time.isoformat()}" if meeting.end_time else None
        short = (meeting.title[:12] + "…") if len(meeting.title or "") > 12 else (meeting.title or "MTG")
        events.append({
            "id": f"mtg-{meeting.id}",
            "title": f"MTG {short}",
            "start": start_dt,
            "end": end_dt,
            "color": NEUTRAL_CAL_BG,
            "textColor": NEUTRAL_CAL_TEXT,
            "extendedProps": {"type": "meeting", "location": meeting.location_text or "", "meeting_title": meeting.title or "", "sort_key": SORT_MTG},
        })


def add_clinic_schedule_events(events: list[dict], db: Session, start_date, end_date) -> None:
    clinic_schedules = db.query(ClinicSchedule).filter(
        ClinicSchedule.date >= start_date,
        ClinicSchedule.date <= end_date,
    ).all()
    for clinic_schedule in clinic_schedules:
        surgeon = clinic_schedule.surgeon
        loc = clinic_schedule.location
        if (clinic_schedule.assignment_type or "assigned") == "off":
            loc_abbrev = "OFF"
        else:
            loc_abbrev = location_abbrev(loc) if loc else "CL"
        short = f"{surgeon_initials(surgeon)} {loc_abbrev}"
        time_slot = "T08:00:00" if clinic_schedule.session == "am" else "T13:00:00" if clinic_schedule.session == "pm" else "T08:00:00"
        loc_hex = "#cbd5e1" if (clinic_schedule.assignment_type or "assigned") == "off" else (loc.color or "#0ea5e9").strip() if loc else "#0ea5e9"
        events.append({
            "id": f"clinic-{clinic_schedule.id}",
            "title": short,
            "start": f"{clinic_schedule.date.isoformat()}{time_slot}",
            "color": pastel_from_location_hex(loc_hex),
            "textColor": "#1e293b",
            "extendedProps": {
                "type": "clinic",
                "surgeon": surgeon.full_name,
                "surgeon_id": surgeon.id,
                "location": "OFF" if (clinic_schedule.assignment_type or "assigned") == "off" else (loc.name if loc else ""),
                "session": clinic_schedule.session,
                "assignment_type": clinic_schedule.assignment_type or "assigned",
                "notes": clinic_schedule.notes or "",
                "sort_key": SORT_CLINIC,
            },
        })


def add_surgery_events(events: list[dict], db: Session, start_date, end_date) -> None:
    surgeries = db.query(SurgicalCase).options(
        joinedload(SurgicalCase.location),
    ).filter(
        SurgicalCase.date >= start_date,
        SurgicalCase.date <= end_date,
        SurgicalCase.status != "cancelled",
    ).all()
    for case in surgeries:
        surgeon = case.surgeon
        loc_name = case.location.name if case.location else (case.room_text or "OR")
        start_dt = f"{case.date.isoformat()}T{case.start_time.isoformat()}" if case.start_time else case.date.isoformat()
        end_dt = f"{case.date.isoformat()}T{case.end_time.isoformat()}" if case.end_time else None
        loc = case.location
        if loc and getattr(loc, "color", None):
            surg_bg = pastel_from_location_hex((loc.color or "").strip())
            surg_tc = "#1e293b"
        else:
            surg_bg = NEUTRAL_CAL_BG
            surg_tc = NEUTRAL_CAL_TEXT
        events.append({
            "id": f"surg-{case.id}",
            "title": f"{surgeon_initials(surgeon)} Sx",
            "start": start_dt,
            "end": end_dt,
            "color": surg_bg,
            "textColor": surg_tc,
            "extendedProps": {
                "type": "surgery",
                "surgeon": surgeon.full_name,
                "surgeon_id": surgeon.id,
                "location": loc_name,
                "procedure": case.procedure,
                "patient_name": case.patient_name,
                "sort_key": SORT_SURG,
            },
        })


def add_unavailable_events(events: list[dict], db: Session, start_date, end_date) -> None:
    unavails = db.query(Availability).filter(
        Availability.date >= start_date,
        Availability.date <= end_date,
        Availability.is_available == False,
    ).all()
    for availability in unavails:
        surgeon = availability.surgeon
        events.append({
            "id": f"unavail-{availability.id}",
            "title": f"{surgeon_initials(surgeon)} NC",
            "start": availability.date.isoformat(),
            "color": NEUTRAL_CAL_BG,
            "textColor": NEUTRAL_CAL_TEXT,
            "display": "background",
            "extendedProps": {"type": "unavailable", "surgeon": surgeon.full_name, "surgeon_id": surgeon.id, "sort_key": SORT_NOCALL},
        })


def build_admin_calendar_events(db: Session, start_date, end_date) -> list[dict]:
    events = []
    add_day_off_events(events, db, start_date, end_date)
    add_call_rotation_events(events, db, start_date, end_date)
    add_meeting_events(events, db, start_date, end_date)
    add_clinic_schedule_events(events, db, start_date, end_date)
    add_surgery_events(events, db, start_date, end_date)
    add_unavailable_events(events, db, start_date, end_date)
    return events


def build_surgeon_calendar_events(db: Session, surgeon, start_date, end_date) -> list[dict]:
    events = []

    rotations = db.query(CallRotation).filter(
        CallRotation.surgeon_id == surgeon.id,
        CallRotation.date >= start_date,
        CallRotation.date <= end_date,
    ).all()
    for rotation in rotations:
        events.append({
            "id": f"rot-{rotation.id}", "title": "🔔 On-Call",
            "start": rotation.date.isoformat(),
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
    for day_off in daysoff:
        events.append({
            "id": f"off-{day_off.id}", "title": "🏖 Day Off",
            "start": day_off.start_date.isoformat(),
            "end": (day_off.end_date + timedelta(days=1)).isoformat(),
            "color": NEUTRAL_CAL_BG,
            "textColor": NEUTRAL_CAL_TEXT,
        })

    for meeting in meetings_for_surgeon(db, surgeon.id, start_date, end_date):
        start_dt = f"{meeting.date.isoformat()}T{meeting.start_time.isoformat()}" if meeting.start_time else meeting.date.isoformat()
        events.append({
            "id": f"mtg-{meeting.id}", "title": f"📋 {meeting.title}",
            "start": start_dt,
            "end": f"{meeting.date.isoformat()}T{meeting.end_time.isoformat()}" if meeting.end_time else None,
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
    for clinic_schedule in my_clinics:
        loc = clinic_schedule.location
        loc_hex = (loc.color or "#0ea5e9").strip() if loc else "#0ea5e9"
        time_slot = "T08:00:00" if clinic_schedule.session == "am" else "T13:00:00" if clinic_schedule.session == "pm" else "T08:00:00"
        loc_label = loc.name if loc else "Clinic"
        events.append({
            "id": f"clinic-{clinic_schedule.id}",
            "title": f"📍 {loc_label}",
            "start": f"{clinic_schedule.date.isoformat()}{time_slot}",
            "color": pastel_from_location_hex(loc_hex),
            "textColor": "#1e293b",
            "extendedProps": {"type": "clinic", "location": loc_label, "session": clinic_schedule.session},
        })

    return events
