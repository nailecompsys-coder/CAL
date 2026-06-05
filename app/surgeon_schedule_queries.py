"""Database query helpers for surgeon schedule views."""

from datetime import date, timedelta

from sqlalchemy import or_
from sqlalchemy.orm import Session, joinedload

from .models import (
    CallGroup,
    CallRotation,
    ClinicSchedule,
    DayOff,
    Meeting,
    MeetingAttendee,
    SurgeonDayItem,
    SurgicalCase,
)


def bucket_rows_by_day(rows, day_attr: str = "date") -> dict:
    grouped = {}
    for row in rows:
        grouped.setdefault(getattr(row, day_attr), []).append(row)
    return grouped


def call_groups(db: Session) -> list[CallGroup]:
    return (
        db.query(CallGroup)
        .order_by(CallGroup.sort_order, CallGroup.name, CallGroup.id)
        .all()
    )


def practice_rotations_by_range(db: Session, start_day: date, end_day: date) -> list[CallRotation]:
    return (
        db.query(CallRotation)
        .options(
            joinedload(CallRotation.surgeon),
            joinedload(CallRotation.call_group),
        )
        .filter(
            CallRotation.date >= start_day,
            CallRotation.date <= end_day,
        )
        .all()
    )


def surgeon_rotations_by_day(db: Session, surgeon_id: int, start_day: date, end_day: date) -> dict:
    return bucket_rows_by_day(
        db.query(CallRotation)
        .filter(
            CallRotation.surgeon_id == surgeon_id,
            CallRotation.date >= start_day,
            CallRotation.date <= end_day,
        )
        .all()
    )


def meetings_for_surgeon_in_range(db: Session, surgeon_id: int, start_day: date, end_day: date) -> list[Meeting]:
    return (
        db.query(Meeting)
        .outerjoin(MeetingAttendee)
        .filter(
            Meeting.date >= start_day,
            Meeting.date <= end_day,
            or_(
                MeetingAttendee.surgeon_id == surgeon_id,
                ~Meeting.attendees.any(),
            ),
        )
        .distinct()
        .order_by(Meeting.date, Meeting.start_time, Meeting.id)
        .all()
    )


def surgeon_meetings_by_day(db: Session, surgeon_id: int, start_day: date, end_day: date) -> dict:
    return bucket_rows_by_day(meetings_for_surgeon_in_range(db, surgeon_id, start_day, end_day))


def surgeon_clinics_by_day(db: Session, surgeon_id: int, start_day: date, end_day: date) -> dict:
    return bucket_rows_by_day(
        db.query(ClinicSchedule)
        .options(joinedload(ClinicSchedule.location))
        .filter(
            ClinicSchedule.surgeon_id == surgeon_id,
            ClinicSchedule.date >= start_day,
            ClinicSchedule.date <= end_day,
        )
        .order_by(ClinicSchedule.date, ClinicSchedule.session, ClinicSchedule.id)
        .all()
    )


def surgeon_surgeries_by_day(db: Session, surgeon_id: int, start_day: date, end_day: date) -> dict:
    return bucket_rows_by_day(
        db.query(SurgicalCase)
        .options(joinedload(SurgicalCase.location))
        .filter(
            SurgicalCase.surgeon_id == surgeon_id,
            SurgicalCase.date >= start_day,
            SurgicalCase.date <= end_day,
            SurgicalCase.status != "cancelled",
        )
        .order_by(SurgicalCase.date, SurgicalCase.start_time, SurgicalCase.id)
        .all()
    )


def surgeon_approved_off_by_day(db: Session, surgeon_id: int, start_day: date, end_day: date) -> dict:
    rows = (
        db.query(DayOff)
        .filter(
            DayOff.surgeon_id == surgeon_id,
            DayOff.start_date <= end_day,
            DayOff.end_date >= start_day,
            DayOff.status == "approved",
        )
        .order_by(DayOff.start_date, DayOff.id)
        .all()
    )
    by_day = {}
    for off in rows:
        span_start = max(off.start_date, start_day)
        span_end = min(off.end_date, end_day)
        d = span_start
        while d <= span_end:
            by_day.setdefault(d, off)
            d += timedelta(days=1)
    return by_day


def off_surgeons_by_day(db: Session, week_start: date, week_end: date) -> dict:
    rows = (
        db.query(DayOff)
        .options(joinedload(DayOff.surgeon))
        .filter(
            DayOff.status == "approved",
            DayOff.start_date <= week_end,
            DayOff.end_date >= week_start,
        )
        .all()
    )
    by_day: dict = {}
    for off in rows:
        surgeon = off.surgeon
        if not surgeon or not surgeon.is_active:
            continue
        span_start = max(off.start_date, week_start)
        span_end = min(off.end_date, week_end)
        d = span_start
        while d <= span_end:
            by_day.setdefault(d, {})[surgeon.id] = surgeon
            d += timedelta(days=1)
    return by_day


def personal_items_by_day(db: Session, surgeon_id: int, week_start: date, week_end: date) -> dict:
    items = (
        db.query(SurgeonDayItem)
        .filter(
            SurgeonDayItem.surgeon_id == surgeon_id,
            SurgeonDayItem.date >= week_start,
            SurgeonDayItem.date <= week_end,
        )
        .order_by(SurgeonDayItem.date, SurgeonDayItem.sort_order, SurgeonDayItem.id)
        .all()
    )
    grouped = {}
    for item in items:
        grouped.setdefault(item.date, []).append(item)
    return grouped
