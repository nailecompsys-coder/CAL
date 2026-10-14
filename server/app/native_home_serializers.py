from __future__ import annotations

from datetime import date
import re

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
        "title": "No Call" if (row.reason or "").strip().lower() == "no call" else "Day Off",
        "subtitle": f"{row.reason or ''}{' · pending' if row.status == 'pending' else ''}".strip(" ·"),
        "start": None if is_full else segment.get("start") or fmt_time(row.start_time),
        "end": None if is_full else segment.get("end") or fmt_time(row.end_time),
        "allDay": is_full,
    }


def meeting_item_payload(meeting) -> dict:
    """Serialize a CAL meetings-table row as type=meeting. No title heuristics."""
    return {
        "id": f"mtg-{meeting.id}",
        "type": "meeting",
        "title": meeting.title,
        "subtitle": meeting.location_text or "",
        "start": fmt_time(meeting.start_time),
        "end": fmt_time(meeting.end_time),
        "notes": meeting.notes or "",
    }


_CLINIC_VISIT_RE = re.compile(r"\b([01]?\d|2[0-3]):([0-5]\d)\s+([^;]+)")


def _clinic_visit_summary(notes: str | None) -> tuple[str | None, int]:
    visits = []
    for match in _CLINIC_VISIT_RE.finditer(notes or ""):
        label = (match.group(3) or "").strip()
        lower = label.lower()
        if "desk fax" in lower or lower.startswith("source=") or lower.startswith("kno2"):
            continue
        visits.append(f"{int(match.group(1)):02d}:{match.group(2)}")
    return (visits[0] if visits else None, len(visits))


def clinic_item_payload(row, start_t: str | None, end_t: str | None) -> dict:
    is_off = (row.assignment_type or "assigned") == "off"
    loc_label = (
        row.location.abbreviation
        if row.location and row.location.abbreviation
        else row.location.name
        if row.location
        else "Clinic"
    )
    if is_off:
        title = "OFF"
    else:
        first_visit, visit_count = _clinic_visit_summary(row.notes)
        if visit_count:
            noun = "patient" if visit_count == 1 else "patients"
            title = f"{loc_label} - {first_visit} - {visit_count} {noun}"
        else:
            title = f"{loc_label} - {start_t or ''}".strip(" -")
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
        "assistingSurgeon": row.assisting_surgeon.full_name if getattr(row, "assisting_surgeon", None) else "",
        "surgeonNotes": row.surgeon_notes or "",
        "color": (row.location.color if row.location else None) or "#e0f2fe",
    }


def aprima_surgery_item_payload(row: dict) -> dict:
    """Native My Schedule item for an Aprima Surgery appointment (read-only from EMR)."""
    from .aprima_schedule_service import is_surgery_appointment, resolve_aprima_facility_name

    appt_id = str(row.get("id") or "")
    site = (row.get("serviceSite") or "").strip()
    room = (row.get("room") or "").strip()
    reason = (row.get("reason") or "").strip()
    appt_type = (row.get("appointmentType") or "Surgery").strip()
    is_surg = is_surgery_appointment(row)
    facility = resolve_aprima_facility_name(site, is_surgery=is_surg)
    needs_review = facility.strip().lower() == "surgery one"
    return {
        "id": f"aprima-surg-{appt_id}",
        "type": "surgery",
        "title": (row.get("patientName") or "").strip() or "Surgery",
        "subtitle": reason or appt_type,
        "start": (row.get("start") or "").strip() or "08:00",
        "end": (row.get("end") or "").strip() or None,
        "location": facility,
        "room": room or site,
        "status": (row.get("status") or "scheduled").strip().lower() or "scheduled",
        "notes": "Aprima review needed" if needs_review else reason,
        "surgeonNotes": "",
        "color": "#dc2626" if needs_review else "#e0f2fe",
        "source": "aprima",
        "needsReview": needs_review,
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
