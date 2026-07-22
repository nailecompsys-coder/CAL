"""Admin calendar API event builders."""

from collections import defaultdict
from datetime import timedelta

from sqlalchemy.orm import Session, joinedload

from .api_calendar_admin_event_serializers import (
    aprima_surgery_event,
    call_rotation_event,
    clinic_schedule_event,
    day_off_event,
    meeting_event,
    surgery_event,
    unavailable_event,
)
from .models import Availability, CallCoverage, CallRotation, ClinicSchedule, DayOff, Meeting, Surgeon, SurgicalCase
from .surgeon_visibility import surgeon_is_visible


def add_day_off_events(events: list[dict], db: Session, start_date, end_date) -> None:
    daysoff = db.query(DayOff).filter(
        DayOff.start_date <= end_date,
        DayOff.end_date >= start_date,
        DayOff.status == "approved",
    ).all()
    by_date = defaultdict(list)
    for day_off in daysoff:
        surgeon = day_off.surgeon
        if not surgeon_is_visible(surgeon):
            continue
        day = max(day_off.start_date, start_date)
        last = min(day_off.end_date, end_date)
        while day <= last:
            by_date[day].append((surgeon, day_off.reason))
            day += timedelta(days=1)
    for day, pairs in by_date.items():
        events.append(day_off_event(day, pairs))


def add_call_rotation_events(events: list[dict], db: Session, start_date, end_date) -> None:
    rotations = db.query(CallRotation).options(
        joinedload(CallRotation.surgeon),
        joinedload(CallRotation.call_group),
        joinedload(CallRotation.coverages).joinedload(CallCoverage.covering_surgeon),
    ).filter(
        CallRotation.date >= start_date,
        CallRotation.date <= end_date,
    ).all()
    for rotation in rotations:
        events.append(call_rotation_event(rotation))


def add_meeting_events(events: list[dict], db: Session, start_date, end_date) -> None:
    meetings = db.query(Meeting).filter(
        Meeting.date >= start_date,
        Meeting.date <= end_date,
    ).all()
    for meeting in meetings:
        events.append(meeting_event(meeting))


def add_clinic_schedule_events(events: list[dict], db: Session, start_date, end_date) -> None:
    clinic_schedules = db.query(ClinicSchedule).filter(
        ClinicSchedule.date >= start_date,
        ClinicSchedule.date <= end_date,
    ).all()
    for clinic_schedule in clinic_schedules:
        if not surgeon_is_visible(clinic_schedule.surgeon):
            continue
        events.append(clinic_schedule_event(clinic_schedule))


def add_surgery_events(events: list[dict], db: Session, start_date, end_date) -> None:
    surgeries = db.query(SurgicalCase).options(
        joinedload(SurgicalCase.location),
    ).filter(
        SurgicalCase.date >= start_date,
        SurgicalCase.date <= end_date,
        SurgicalCase.status != "cancelled",
    ).all()
    for case in surgeries:
        if not surgeon_is_visible(case.surgeon):
            continue
        events.append(surgery_event(case))


def add_aprima_surgery_events(events: list[dict], db: Session, start_date, end_date) -> None:
    """Aprima EMR Surgery appointments on the admin FullCalendar."""
    from .aprima_cache_service import patient_appointments_for_api
    from .aprima_schedule_service import appointment_belongs_to_surgeon, is_surgery_appointment

    payload = patient_appointments_for_api(db, start_date, end_date, surgeon=None)
    surgeons = [
        row for row in db.query(Surgeon).filter(Surgeon.is_active == True).all()  # noqa: E712
        if surgeon_is_visible(row)
    ]
    for row in payload.get("appointments") or []:
        if not is_surgery_appointment(row):
            continue
        matched = next((s for s in surgeons if appointment_belongs_to_surgeon(row, s)), None)
        if matched is None:
            continue
        events.append(aprima_surgery_event(row, matched))


def add_unavailable_events(events: list[dict], db: Session, start_date, end_date) -> None:
    unavails = db.query(Availability).filter(
        Availability.date >= start_date,
        Availability.date <= end_date,
        Availability.is_available == False,
    ).all()
    for availability in unavails:
        if not surgeon_is_visible(availability.surgeon):
            continue
        events.append(unavailable_event(availability))


def build_admin_calendar_events(db: Session, start_date, end_date) -> list[dict]:
    events = []
    add_day_off_events(events, db, start_date, end_date)
    add_call_rotation_events(events, db, start_date, end_date)
    add_meeting_events(events, db, start_date, end_date)
    add_clinic_schedule_events(events, db, start_date, end_date)
    add_surgery_events(events, db, start_date, end_date)
    add_aprima_surgery_events(events, db, start_date, end_date)
    add_unavailable_events(events, db, start_date, end_date)
    return events
