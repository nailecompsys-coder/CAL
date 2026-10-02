"""Native home payload item and lookup helpers."""

from datetime import date, timedelta

from sqlalchemy import case, func
from sqlalchemy.orm import Session, joinedload

from .models import (
    Availability,
    CallGroup,
    CallCoverage,
    CallRotation,
    DayOff,
    Surgeon,
    SurgeonDayItem,
)
from .native_home_serializers import (
    aprima_surgery_item_payload,
    availability_payload,
    call_item_payload,
    day_off_item_payload,
    empty_day_payload,
    meeting_item_payload,
    personal_item_payload,
    surgeon_payload,
)
from .native_support import (
    active_coverage_for_rotation,
    meetings_for_surgeon,
    segment_for_date,
    serialize_day_off,
)


def empty_days(start_date: date, end_date: date) -> list[dict]:
    days = []
    current = start_date
    while current <= end_date:
        days.append(empty_day_payload(current))
        current += timedelta(days=1)
    return days


def my_day_off_rows(db: Session, surgeon: Surgeon, start_date: date, end_date: date) -> list[DayOff]:
    return db.query(DayOff).filter(
        DayOff.surgeon_id == surgeon.id,
        DayOff.start_date <= end_date,
        DayOff.end_date >= start_date,
        DayOff.status.in_(["pending", "approved"]),
    ).all()


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
            by_date[rotation.date.isoformat()]["items"].append(call_item_payload(rotation, coverage, surgeon.id))


def append_my_day_off_items(day_off_rows: list[DayOff], start_date: date, end_date: date, by_date: dict) -> None:
    for row in day_off_rows:
        span = max(row.start_date, start_date)
        span_end = min(row.end_date, end_date)
        while span <= span_end:
            segment = segment_for_date(row, span) or {}
            is_full = segment.get("isFullDay", row.is_full_day if row.is_full_day is not None else True)
            by_date[span.isoformat()]["items"].append(day_off_item_payload(row, span, segment, is_full))
            span += timedelta(days=1)


def append_meetings(db: Session, surgeon: Surgeon, start_date: date, end_date: date, by_date: dict) -> None:
    for meeting in meetings_for_surgeon(db, surgeon.id, start_date, end_date):
        by_date[meeting.date.isoformat()]["items"].append(meeting_item_payload(meeting))


def append_aprima_surgery_items(
    db: Session,
    surgeon: Surgeon,
    start_date: date,
    end_date: date,
    by_date: dict,
) -> None:
    """Aprima EMR appointments on Clinic / OR schedule.

    Every harvested Aprima patient is Surgery One, at whatever clinic or hospital
    they are seen. Surgeries map onto hospital OR names; clinic visits keep the
    site (Clermont → Surgery One, Lake Mary Clinic, …).
    """
    from .aprima_cache_service import patient_appointments_for_api

    payload = patient_appointments_for_api(db, start_date, end_date, surgeon=surgeon)
    for row in payload.get("appointments") or []:
        day_key = (row.get("date") or "").strip()
        if day_key not in by_date:
            continue
        by_date[day_key]["items"].append(aprima_surgery_item_payload(row))


def append_personal_items(db: Session, surgeon: Surgeon, start_date: date, end_date: date, by_date: dict) -> None:
    for row in db.query(SurgeonDayItem).filter(
        SurgeonDayItem.surgeon_id == surgeon.id,
        SurgeonDayItem.date >= start_date,
        SurgeonDayItem.date <= end_date,
    ).order_by(SurgeonDayItem.date, SurgeonDayItem.sort_order, SurgeonDayItem.id).all():
        by_date[row.date.isoformat()]["items"].append(personal_item_payload(row))


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
        rows.append(availability_payload(day, rec))
    return rows


def requests(db: Session, surgeon: Surgeon, today: date) -> list[dict]:
    return [
        serialize_day_off(row)
        for row in db.query(DayOff).filter(
            DayOff.surgeon_id == surgeon.id,
            DayOff.end_date >= today - timedelta(days=30),
        ).order_by(DayOff.start_date.asc(), DayOff.id.asc()).limit(50).all()
    ]


def call_groups(db: Session) -> list[CallGroup]:
    return db.query(CallGroup).order_by(CallGroup.sort_order, CallGroup.name, CallGroup.id).all()


def surgeons(db: Session) -> list[dict]:
    return [
        surgeon_payload(row)
        for row in db.query(Surgeon).filter(
            Surgeon.is_active == True,  # noqa: E712
            func.lower(func.coalesce(Surgeon.email, "")) != "don@clermontitstore.com",
            ~((Surgeon.first_name.ilike("developer")) & (Surgeon.last_name.ilike("admin"))),
        ).order_by(
            case((func.coalesce(Surgeon.staff_type, "physician") == "physician", 0), else_=1),
            case((
                (func.coalesce(Surgeon.staff_type, "physician") == "physician") & (Surgeon.sort_order > 0),
                Surgeon.sort_order,
            ), else_=999999),
            Surgeon.last_name,
            Surgeon.first_name,
            Surgeon.id,
        ).all()
    ]
