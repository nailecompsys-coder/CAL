"""Native home payload item and lookup helpers."""

from datetime import date, timedelta

from sqlalchemy.orm import Session, joinedload

from .models import (
    Availability,
    CallGroup,
    CallCoverage,
    CallRotation,
    ClinicSchedule,
    DayOff,
    Surgeon,
    SurgeonDayItem,
    SurgicalCase,
)
from .native_support import (
    active_coverage_for_rotation,
    date_label,
    fmt_time,
    meetings_for_surgeon,
    native_surgeon_rank_key,
    parse_hhmm,
    segment_for_date,
    serialize_day_off,
    session_times,
)


def empty_days(start_date: date, end_date: date) -> list[dict]:
    days = []
    current = start_date
    while current <= end_date:
        days.append({
            **date_label(current),
            "items": [],
            "offSurgeons": [],
            "requestedOffSurgeons": [],
            "callAssignments": [],
        })
        current += timedelta(days=1)
    return days


def my_day_off_rows(db: Session, surgeon: Surgeon, start_date: date, end_date: date) -> list[DayOff]:
    return db.query(DayOff).filter(
        DayOff.surgeon_id == surgeon.id,
        DayOff.start_date <= end_date,
        DayOff.end_date >= start_date,
        DayOff.status.in_(["pending", "approved"]),
    ).all()


def blocked_by_day_off(day_off_rows: list[DayOff], item_date: date, start_t: str | None = None, end_t: str | None = None) -> bool:
    for off in day_off_rows:
        if off.start_date <= item_date <= off.end_date:
            segment = segment_for_date(off, item_date)
            if segment and segment.get("isFullDay"):
                return True
            seg_start = parse_hhmm(segment.get("start")) if segment else off.start_time
            seg_end = parse_hhmm(segment.get("end")) if segment else off.end_time
            if not seg_start or not seg_end:
                return True
            if not start_t:
                return True
            item_start = parse_hhmm(start_t)
            item_end = parse_hhmm(end_t) or item_start
            if item_start and item_end and item_start < seg_end and item_end > seg_start:
                return True
    return False


def append_my_call_items(db: Session, surgeon: Surgeon, start_date: date, end_date: date, by_date: dict) -> None:
    for rotation in db.query(CallRotation).options(
        joinedload(CallRotation.call_group),
        joinedload(CallRotation.coverages).joinedload(CallCoverage.covering_surgeon),
        joinedload(CallRotation.surgeon),
    ).filter(
        CallRotation.date >= start_date,
        CallRotation.date <= end_date,
    ).all():
        coverage = active_coverage_for_rotation(rotation)
        if rotation.surgeon_id == surgeon.id or (coverage and coverage.covering_surgeon_id == surgeon.id):
            by_date[rotation.date.isoformat()]["items"].append({
                "id": f"rot-{rotation.id}",
                "rawId": rotation.id,
                "type": "oncall",
                "title": "On-Call Coverage" if coverage and coverage.covering_surgeon_id == surgeon.id else "On-Call",
                "subtitle": rotation.call_group.name if rotation.call_group else "",
                "allDay": True,
            })


def append_my_day_off_items(day_off_rows: list[DayOff], start_date: date, end_date: date, by_date: dict) -> None:
    for row in day_off_rows:
        span = max(row.start_date, start_date)
        span_end = min(row.end_date, end_date)
        while span <= span_end:
            segment = segment_for_date(row, span) or {}
            is_full = segment.get("isFullDay", row.is_full_day if row.is_full_day is not None else True)
            by_date[span.isoformat()]["items"].append({
                "id": f"off-{row.id}-{span.isoformat()}",
                "type": "dayoff",
                "title": "Day Off",
                "subtitle": f"{row.reason or ''}{' · pending' if row.status == 'pending' else ''}".strip(" ·"),
                "start": None if is_full else segment.get("start") or fmt_time(row.start_time),
                "end": None if is_full else segment.get("end") or fmt_time(row.end_time),
                "allDay": is_full,
            })
            span += timedelta(days=1)


def append_meetings(db: Session, surgeon: Surgeon, start_date: date, end_date: date, by_date: dict) -> None:
    for meeting in meetings_for_surgeon(db, surgeon.id, start_date, end_date):
        by_date[meeting.date.isoformat()]["items"].append({
            "id": f"mtg-{meeting.id}",
            "type": "meeting",
            "title": meeting.title,
            "subtitle": meeting.location_text or "",
            "start": fmt_time(meeting.start_time),
            "end": fmt_time(meeting.end_time),
            "notes": meeting.notes or "",
        })


def append_clinic_items(db: Session, surgeon: Surgeon, start_date: date, end_date: date, by_date: dict, day_off_rows: list[DayOff]) -> None:
    for row in db.query(ClinicSchedule).options(joinedload(ClinicSchedule.location)).filter(
        ClinicSchedule.surgeon_id == surgeon.id,
        ClinicSchedule.date >= start_date,
        ClinicSchedule.date <= end_date,
    ).order_by(ClinicSchedule.date, ClinicSchedule.session, ClinicSchedule.id).all():
        start_t, end_t = session_times(row.session)
        if blocked_by_day_off(day_off_rows, row.date, start_t, end_t):
            continue
        title = "OFF" if (row.assignment_type or "assigned") == "off" else (row.location.name if row.location else "Clinic")
        by_date[row.date.isoformat()]["items"].append({
            "id": f"clinic-{row.id}",
            "type": "clinic",
            "title": title,
            "subtitle": (row.session or "full").upper(),
            "start": start_t,
            "end": end_t,
            "color": "#cbd5e1" if title == "OFF" else ((row.location.color if row.location else None) or "#0ea5e9"),
            "notes": row.notes or "",
        })


def append_surgical_items(db: Session, surgeon: Surgeon, start_date: date, end_date: date, by_date: dict, day_off_rows: list[DayOff]) -> None:
    for row in db.query(SurgicalCase).options(joinedload(SurgicalCase.location)).filter(
        SurgicalCase.surgeon_id == surgeon.id,
        SurgicalCase.date >= start_date,
        SurgicalCase.date <= end_date,
        SurgicalCase.status != "cancelled",
    ).order_by(SurgicalCase.date, SurgicalCase.start_time, SurgicalCase.id).all():
        if blocked_by_day_off(day_off_rows, row.date, fmt_time(row.start_time), fmt_time(row.end_time)):
            continue
        by_date[row.date.isoformat()]["items"].append({
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
        })


def append_personal_items(db: Session, surgeon: Surgeon, start_date: date, end_date: date, by_date: dict) -> None:
    for row in db.query(SurgeonDayItem).filter(
        SurgeonDayItem.surgeon_id == surgeon.id,
        SurgeonDayItem.date >= start_date,
        SurgeonDayItem.date <= end_date,
    ).order_by(SurgeonDayItem.date, SurgeonDayItem.sort_order, SurgeonDayItem.id).all():
        by_date[row.date.isoformat()]["items"].append({
            "id": f"personal-{row.id}",
            "rawId": row.id,
            "type": "personal",
            "title": row.title,
            "subtitle": row.notes or "",
            "start": fmt_time(row.start_time),
            "end": fmt_time(row.end_time),
            "notes": row.notes or "",
        })


def sort_day_items(days: list[dict]) -> None:
    for day in days:
        day["items"].sort(key=lambda item: (item.get("start") or "99:99", item["type"], item["title"]))


def availability(db: Session, surgeon: Surgeon, today: date) -> list[dict]:
    avail_records = db.query(Availability).filter(
        Availability.surgeon_id == surgeon.id,
        Availability.date >= today,
        Availability.date <= today + timedelta(days=27),
    ).order_by(Availability.date).all()
    avail_map = {row.date: row for row in avail_records}
    rows = []
    for i in range(28):
        day = today + timedelta(days=i)
        rec = avail_map.get(day)
        rows.append({
            **date_label(day),
            "isAvailable": rec.is_available if rec else True,
            "start": fmt_time(rec.start_time) if rec else None,
            "end": fmt_time(rec.end_time) if rec else None,
        })
    return rows


def requests(db: Session, surgeon: Surgeon, today: date) -> list[dict]:
    return [
        serialize_day_off(row)
        for row in db.query(DayOff).filter(
            DayOff.surgeon_id == surgeon.id,
            DayOff.end_date >= today - timedelta(days=30),
        ).order_by(DayOff.start_date.desc(), DayOff.id.desc()).limit(50).all()
    ]


def call_groups(db: Session) -> list[CallGroup]:
    return db.query(CallGroup).order_by(CallGroup.sort_order, CallGroup.name, CallGroup.id).all()


def surgeons(db: Session) -> list[dict]:
    return [
        {"id": row.id, "name": row.full_name, "initials": row.initials, "staffType": row.staff_type, "sortOrder": row.sort_order or 0}
        for row in sorted(
            db.query(Surgeon).filter(Surgeon.is_active == True).all(),  # noqa: E712
            key=native_surgeon_rank_key,
        )
    ]
