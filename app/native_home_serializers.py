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


def meeting_item_payload(meeting) -> dict:
    return {
        "id": f"mtg-{meeting.id}",
        "type": "meeting",
        "title": meeting.title,
        "subtitle": meeting.location_text or "",
        "start": fmt_time(meeting.start_time),
        "end": fmt_time(meeting.end_time),
        "notes": meeting.notes or "",
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
