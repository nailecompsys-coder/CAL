"""Serialization helpers for surgeon schedule views."""

import json

from .models import Surgeon
from .routers.surgeon_context import serialize_personal_item


def session_times(session: str):
    if session == "am":
        return ("08:00", "12:00")
    if session == "pm":
        return ("13:00", "17:00")
    return ("08:00", "17:00")


def serialize_off_surgeon(surgeon: Surgeon, viewer_id: int) -> dict:
    return {
        "initials": surgeon.initials,
        "displayName": surgeon.full_name,
        "isSelf": surgeon.id == viewer_id,
    }


def serialize_schedule_day(
    day,
    rotations,
    day_off,
    meetings,
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
        "clinics": [
            {
                "name": "OFF" if (cs.assignment_type or "assigned") == "off" else cs.location.name,
                "color": "#cbd5e1" if (cs.assignment_type or "assigned") == "off" else (cs.location.color or "#0ea5e9"),
                "session": cs.session,
                "start": session_times(cs.session)[0],
                "end": session_times(cs.session)[1],
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
                "assistingSurgeon": sc.assisting_surgeon.full_name if sc.assisting_surgeon else "",
                "surgeonNotes": sc.surgeon_notes or "",
                "color": (sc.location.color or None) if sc.location else None,
                "source": getattr(sc, "source", None) or "cal",
                "readOnly": getattr(sc, "source", None) == "aprima",
            }
            for sc in surgeries
        ],
        "offSurgeons": [serialize_off_surgeon(s, viewer_id) for s in off_surgeons],
        "personalItems": [serialize_personal_item(p) for p in personal_items],
    }


def serialize_schedule_week(week_summary: list[dict], surgeon_id: int) -> str:
    return json.dumps([
        serialize_schedule_day(
            ws["date"],
            ws["rotations"],
            ws["day_off"],
            ws["meetings"],
            ws["clinics"],
            ws["surgeries"],
            ws["off_surgeons"],
            ws["personal_items"],
            surgeon_id,
            call_group_rail=ws["serialized_call_rail"],
        )
        for ws in week_summary
    ])
