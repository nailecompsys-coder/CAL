from __future__ import annotations

from .api_calendar_utils import (
    NEUTRAL_CAL_BG,
    NEUTRAL_CAL_TEXT,
    SORT_CALL,
    SORT_CLINIC,
    SORT_DAYOFF,
    SORT_MTG,
    SORT_NOCALL,
    SORT_SURG,
    call_group_abbrev,
    location_abbrev,
    pastel_from_location_hex,
    surgeon_initials,
)
from .native_call_support import active_coverage_for_rotation
from .surgeon_visibility import surgeon_is_visible


def day_off_event(day, pairs: list[tuple]) -> dict:
    initials_list = []
    surgeon_ids = []
    names_for_modal = []
    for surgeon, _reason in pairs:
        initials_list.append(surgeon_initials(surgeon))
        surgeon_ids.append(surgeon.id)
        names_for_modal.append(surgeon.full_name)
    return {
        "id": f"off-{day.isoformat()}",
        "title": " ".join(initials_list) + " OFF",
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
    }


def call_rotation_event(rotation) -> dict:
    original_surgeon = rotation.surgeon
    coverage = active_coverage_for_rotation(rotation)
    covering_surgeon = coverage.covering_surgeon if coverage else None
    surgeon = covering_surgeon or (original_surgeon if surgeon_is_visible(original_surgeon) else None)
    group = rotation.call_group
    group_name = group.name if group else ""
    group_abbrev = call_group_abbrev(group_name) if group else "?"
    if not surgeon:
        return {
            "id": f"rot-{rotation.id}",
            "title": f"{group_abbrev} NC",
            "start": rotation.date.isoformat(),
            "color": NEUTRAL_CAL_BG,
            "textColor": NEUTRAL_CAL_TEXT,
            "extendedProps": {"type": "oncall", "surgeon_id": None, "surgeon": "", "call_group": group_name, "role": "nc", "sort_key": SORT_NOCALL},
        }
    return {
        "id": f"rot-{rotation.id}",
        "title": f"{group_abbrev}: {surgeon_initials(surgeon)}",
        "start": rotation.date.isoformat(),
        "color": NEUTRAL_CAL_BG,
        "textColor": NEUTRAL_CAL_TEXT,
        "extendedProps": {
            "type": "oncall",
            "surgeon": surgeon.full_name,
            "surgeon_id": surgeon.id,
            "original_surgeon": original_surgeon.full_name if surgeon_is_visible(original_surgeon) else "",
            "original_surgeon_id": original_surgeon.id if surgeon_is_visible(original_surgeon) else None,
            "original_initials": surgeon_initials(original_surgeon) if surgeon_is_visible(original_surgeon) else "NC",
            "covering_surgeon": covering_surgeon.full_name if covering_surgeon else None,
            "covering_surgeon_id": covering_surgeon.id if covering_surgeon else None,
            "covering_initials": surgeon_initials(covering_surgeon) if covering_surgeon else None,
            "is_covered": coverage is not None,
            "coverage_id": coverage.id if coverage else None,
            "call_group": group_name,
            "sort_key": SORT_CALL,
        },
    }


def meeting_event(meeting) -> dict:
    start_dt = f"{meeting.date.isoformat()}T{meeting.start_time.isoformat()}" if meeting.start_time else meeting.date.isoformat()
    end_dt = f"{meeting.date.isoformat()}T{meeting.end_time.isoformat()}" if meeting.end_time else None
    short = (meeting.title[:12] + "…") if len(meeting.title or "") > 12 else (meeting.title or "MTG")
    return {
        "id": f"mtg-{meeting.id}",
        "title": f"MTG {short}",
        "start": start_dt,
        "end": end_dt,
        "color": NEUTRAL_CAL_BG,
        "textColor": NEUTRAL_CAL_TEXT,
        "extendedProps": {"type": "meeting", "location": meeting.location_text or "", "meeting_title": meeting.title or "", "sort_key": SORT_MTG},
    }


def clinic_schedule_event(clinic_schedule) -> dict:
    surgeon = clinic_schedule.surgeon
    loc = clinic_schedule.location
    loc_abbrev = "OFF" if (clinic_schedule.assignment_type or "assigned") == "off" else (location_abbrev(loc) if loc else "CL")
    time_slot = "T08:00:00" if clinic_schedule.session == "am" else "T13:00:00" if clinic_schedule.session == "pm" else "T08:00:00"
    loc_hex = "#cbd5e1" if (clinic_schedule.assignment_type or "assigned") == "off" else (loc.color or "#0ea5e9").strip() if loc else "#0ea5e9"
    return {
        "id": f"clinic-{clinic_schedule.id}",
        "title": f"{surgeon_initials(surgeon)} {loc_abbrev}",
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
    }


def surgery_event(case) -> dict:
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
    return {
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
    }


def aprima_surgery_event(row: dict, surgeon) -> dict:
    """Admin calendar event for an Aprima Surgery appointment."""
    day = (row.get("date") or "").strip()
    start = (row.get("start") or "").strip()
    end = (row.get("end") or "").strip()
    start_dt = f"{day}T{start}:00" if day and start else day
    end_dt = f"{day}T{end}:00" if day and end else None
    site = (row.get("serviceSite") or "").strip() or "Surgery"
    appt_id = str(row.get("id") or "")
    return {
        "id": f"aprima-surg-{appt_id}",
        "title": f"{surgeon_initials(surgeon)} Sx",
        "start": start_dt,
        "end": end_dt,
        "color": NEUTRAL_CAL_BG,
        "textColor": NEUTRAL_CAL_TEXT,
        "extendedProps": {
            "type": "surgery",
            "source": "aprima",
            "surgeon": surgeon.full_name,
            "surgeon_id": surgeon.id,
            "location": site,
            "procedure": (row.get("reason") or row.get("appointmentType") or "Surgery"),
            "patient_name": row.get("patientName") or "",
            "room": row.get("room") or "",
            "sort_key": SORT_SURG,
        },
    }


def unavailable_event(availability) -> dict:
    surgeon = availability.surgeon
    return {
        "id": f"unavail-{availability.id}",
        "title": f"{surgeon_initials(surgeon)} NC",
        "start": availability.date.isoformat(),
        "color": NEUTRAL_CAL_BG,
        "textColor": NEUTRAL_CAL_TEXT,
        "display": "background",
        "extendedProps": {"type": "unavailable", "surgeon": surgeon.full_name, "surgeon_id": surgeon.id, "sort_key": SORT_NOCALL},
    }
