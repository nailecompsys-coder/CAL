from __future__ import annotations

from datetime import date

from .native_support import date_label, fmt_time


def empty_day_payload(day: date) -> dict:
    return {
        **date_label(day),
        "items": [],
        "offSurgeons": [],
        "requestedOffSurgeons": [],
        "callAssignments": [],
    }


def call_item_payload(rotation, coverage, surgeon_id: int) -> dict:
    return {
        "id": f"rot-{rotation.id}",
        "rawId": rotation.id,
        "type": "oncall",
        "title": "On-Call Coverage" if coverage and coverage.covering_surgeon_id == surgeon_id else "On-Call",
        "subtitle": rotation.call_group.name if rotation.call_group else "",
        "allDay": True,
    }


def day_off_item_payload(row, item_date: date, segment: dict, is_full: bool) -> dict:
    return {
        "id": f"off-{row.id}-{item_date.isoformat()}",
        "type": "dayoff",
        "title": "Day Off",
        "subtitle": f"{row.reason or ''}{' · pending' if row.status == 'pending' else ''}".strip(" ·"),
        "start": None if is_full else segment.get("start") or fmt_time(row.start_time),
        "end": None if is_full else segment.get("end") or fmt_time(row.end_time),
        "allDay": is_full,
    }


_CLINIC_ROTATION_TITLE_MARKERS = (
    "surgery 1",
    "surgery one",
    "surgical 1",
    "surgical one",
)
_CLINIC_ROTATION_LOCATIONS = {
    "cbo",
    "surgery one",
    "surgery 1",
    "surgical one",
    "surgical 1",
}


def is_clinic_rotation_text(*, title: str = "", location: str = "", reason: str = "") -> bool:
    """True when labeling describes Surgery One / clinic rotation time, not a real meeting."""
    title_l = (title or "").strip().lower()
    location_l = (location or "").strip().lower()
    reason_l = (reason or "").strip().lower()
    blob = f"{title_l} {reason_l}".strip()
    if not blob and not location_l:
        return False
    if "cancel" in title_l or "cancel" in reason_l:
        return False
    if "clinic" in title_l or "clinic" in reason_l:
        return True
    if location_l in _CLINIC_ROTATION_LOCATIONS:
        return True
    return any(marker in blob for marker in _CLINIC_ROTATION_TITLE_MARKERS)


def is_clinic_day_meeting(meeting) -> bool:
    """True when a CAL Meeting row is really a clinic-day assignment (e.g. Surgery 1 / CBO).

    Practice staff often enter recurring clinic days in the Meetings table. Those should
    render under My Schedule / clinic schedule, not the Meetings list.
    """
    return is_clinic_rotation_text(
        title=getattr(meeting, "title", None) or "",
        location=getattr(meeting, "location_text", None) or "",
        reason=getattr(meeting, "notes", None) or "",
    )


def meeting_item_payload(meeting) -> dict:
    if is_clinic_day_meeting(meeting):
        return clinic_day_meeting_item_payload(meeting)
    return {
        "id": f"mtg-{meeting.id}",
        "type": "meeting",
        "title": meeting.title,
        "subtitle": meeting.location_text or "",
        "start": fmt_time(meeting.start_time),
        "end": fmt_time(meeting.end_time),
        "notes": meeting.notes or "",
    }


def clinic_day_meeting_item_payload(meeting) -> dict:
    """Serialize a clinic-day Meeting as a clinic schedule item for My Schedule."""
    import re

    title = (meeting.title or "").strip() or "Clinic"
    # Drop leading surgeon initials ("CJ Surgery 1 Clinic" -> "Surgery 1 Clinic")
    title = re.sub(r"^[A-Z]{1,4}\s+", "", title).strip() or title
    location = (meeting.location_text or "").strip()
    if location and location.lower() not in title.lower():
        display = f"{location} · {title}"
    else:
        display = title
    return {
        "id": f"clinic-mtg-{meeting.id}",
        "rawId": meeting.id,
        "type": "clinic",
        "title": display,
        "subtitle": "CLINIC",
        "start": fmt_time(meeting.start_time),
        "end": fmt_time(meeting.end_time),
        "location": location,
        "notes": meeting.notes or "",
        "color": "#0ea5e9",
    }


def clinic_item_payload(row, start_t: str | None, end_t: str | None) -> dict:
    title = "OFF" if (row.assignment_type or "assigned") == "off" else (row.location.name if row.location else "Clinic")
    return {
        "id": f"clinic-{row.id}",
        "type": "clinic",
        "title": title,
        "subtitle": (row.session or "full").upper(),
        "start": start_t,
        "end": end_t,
        "color": "#cbd5e1" if title == "OFF" else ((row.location.color if row.location else None) or "#0ea5e9"),
        "notes": row.notes or "",
    }


def surgical_item_payload(row) -> dict:
    return {
        "id": f"surg-{row.id}",
        "rawId": row.id,
        "type": "surgery",
        "title": row.patient_name or "Surgery",
        "subtitle": row.procedure or "",
        "start": fmt_time(row.start_time) or "08:00",
        "end": fmt_time(row.end_time),
        "location": (row.location.name if row.location else "") or row.room_text or "",
        "room": row.room_text or "",
        "status": row.status or "scheduled",
        "notes": row.notes or "",
        "surgeonNotes": row.surgeon_notes or "",
        "color": (row.location.color if row.location else None) or "#e0f2fe",
    }


def aprima_surgery_item_payload(row: dict) -> dict:
    """Native My Schedule item for an Aprima Surgery appointment (read-only from EMR)."""
    appt_id = str(row.get("id") or "")
    site = (row.get("serviceSite") or "").strip()
    room = (row.get("room") or "").strip()
    reason = (row.get("reason") or "").strip()
    appt_type = (row.get("appointmentType") or "Surgery").strip()
    return {
        "id": f"aprima-surg-{appt_id}",
        "type": "surgery",
        "title": (row.get("patientName") or "").strip() or "Surgery",
        "subtitle": reason or appt_type,
        "start": (row.get("start") or "").strip() or "08:00",
        "end": (row.get("end") or "").strip() or None,
        "location": site,
        "room": room,
        "status": (row.get("status") or "scheduled").strip().lower() or "scheduled",
        "notes": reason,
        "surgeonNotes": "",
        "color": "#e0f2fe",
        "source": "aprima",
        "readOnly": True,
    }


def block_or_item_payload(row, assignments=None) -> dict:
    location = row.location.abbreviation if row.location and row.location.abbreviation else (row.location.name if row.location else "OR")
    assignments = assignments or []
    if assignments:
        start = fmt_time(min(assignment.start_time for assignment in assignments)) or fmt_time(row.start_time) or "07:00"
        cases = sum(assignment.case_count or 0 for assignment in assignments)
        notes = "; ".join(filter(None, [assignment.note for assignment in assignments]))
    else:
        start = fmt_time(row.assigned_start_time) or fmt_time(row.start_time) or "07:00"
        cases = row.assigned_case_count or 0
        notes = row.assignment_note or row.notes or ""
    return {
        "id": f"block-or-{row.id}",
        "rawId": row.id,
        "type": "block_or",
        "title": f"{location} - {start} - {cases} Case{'s' if cases != 1 else ''}",
        "subtitle": "Block OR",
        "start": start,
        "end": fmt_time(row.end_time),
        "location": location,
        "notes": notes,
        "color": (row.location.color if row.location else None) or "#d9f99d",
    }


def personal_item_payload(row) -> dict:
    return {
        "id": f"personal-{row.id}",
        "rawId": row.id,
        "type": "personal",
        "title": row.title,
        "subtitle": row.notes or "",
        "start": fmt_time(row.start_time),
        "end": fmt_time(row.end_time),
        "notes": row.notes or "",
    }


def availability_payload(day: date, record) -> dict:
    return {
        **date_label(day),
        "isAvailable": record.is_available if record else True,
        "start": fmt_time(record.start_time) if record else None,
        "end": fmt_time(record.end_time) if record else None,
    }


def surgeon_payload(row) -> dict:
    return {
        "id": row.id,
        "name": row.full_name,
        "initials": row.initials,
        "staffType": row.staff_type,
        "sortOrder": row.sort_order or 0,
    }
