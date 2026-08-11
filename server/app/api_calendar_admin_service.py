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
from .api_calendar_utils import SORT_DAYOFF
from .models import Availability, CallCoverage, CallRotation, ClinicSchedule, DayOff, Meeting, Surgeon, SurgicalCase
from .surgeon_visibility import surgeon_is_visible


def add_day_off_events(events: list[dict], db: Session, start_date, end_date) -> None:
    daysoff = db.query(DayOff).filter(
        DayOff.start_date <= end_date,
        DayOff.end_date >= start_date,
        DayOff.status.in_(("approved", "pending")),
    ).all()
    by_date = defaultdict(list)
    # Prefer approved when both exist for same surgeon/day
    seen: dict[tuple, str] = {}
    for day_off in daysoff:
        surgeon = day_off.surgeon
        if not surgeon_is_visible(surgeon):
            continue
        day = max(day_off.start_date, start_date)
        last = min(day_off.end_date, end_date)
        while day <= last:
            key = (day, surgeon.id)
            prev = seen.get(key)
            if prev == "approved":
                day += timedelta(days=1)
                continue
            if day_off.status == "approved" or not prev:
                # Replace pending entry if upgrading to approved
                if prev == "pending":
                    by_date[day] = [
                        p for p in by_date[day]
                        if not (p[0].id == surgeon.id and (len(p) < 3 or p[2] == "pending"))
                    ]
                by_date[day].append((surgeon, day_off.reason, day_off.status))
                seen[key] = day_off.status
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


def add_clinic_schedule_events(
    events: list[dict],
    db: Session,
    start_date,
    end_date,
    *,
    show_off_schedule_ids: set[int] | None = None,
    conflict_keys: set[tuple] | None = None,
) -> None:
    clinic_schedules = db.query(ClinicSchedule).filter(
        ClinicSchedule.date >= start_date,
        ClinicSchedule.date <= end_date,
    ).all()
    show_off_schedule_ids = show_off_schedule_ids or set()
    conflict_keys = conflict_keys or set()
    for clinic_schedule in clinic_schedules:
        if not surgeon_is_visible(clinic_schedule.surgeon):
            continue
        # Empty clinic/OR on OFF day → omit location pill (OFF row covers it)
        if clinic_schedule.id in show_off_schedule_ids:
            continue
        event = clinic_schedule_event(clinic_schedule)
        if (clinic_schedule.surgeon_id, clinic_schedule.date) in conflict_keys:
            event["extendedProps"]["off_conflict"] = True
            event["title"] = f"⚠ {event['title']}"
        events.append(event)


def add_surgery_events(
    events: list[dict],
    db: Session,
    start_date,
    end_date,
    *,
    conflict_keys: set[tuple] | None = None,
) -> None:
    surgeries = db.query(SurgicalCase).options(
        joinedload(SurgicalCase.location),
    ).filter(
        SurgicalCase.date >= start_date,
        SurgicalCase.date <= end_date,
        SurgicalCase.status != "cancelled",
    ).all()
    conflict_keys = conflict_keys or set()
    for case in surgeries:
        if not surgeon_is_visible(case.surgeon):
            continue
        event = surgery_event(case)
        if (case.surgeon_id, case.date) in conflict_keys:
            event["extendedProps"]["off_conflict"] = True
            event["title"] = f"⚠ {event['title']}"
        events.append(event)


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
    from .off_conflict_service import build_clinic_off_display

    schedules = db.query(ClinicSchedule).filter(
        ClinicSchedule.date >= start_date,
        ClinicSchedule.date <= end_date,
    ).all()
    sched_map: dict = {}
    for schedule in schedules:
        sched_map.setdefault(schedule.surgeon_id, {}).setdefault(schedule.date, []).append(schedule)

    surgeries = db.query(SurgicalCase).filter(
        SurgicalCase.date >= start_date,
        SurgicalCase.date <= end_date,
        SurgicalCase.status != "cancelled",
    ).all()
    surgical_map: dict = {}
    for case in surgeries:
        surgical_map.setdefault(case.surgeon_id, {}).setdefault(case.date, []).append(case)

    off_display = build_clinic_off_display(
        db,
        start_date,
        end_date,
        sched_map=sched_map,
        surgical_map=surgical_map,
    )
    conflict_keys = off_display["conflict_keys"]
    show_off_schedule_ids = off_display["show_off_schedule_ids"]

    events = []
    add_day_off_events(events, db, start_date, end_date)
    add_call_rotation_events(events, db, start_date, end_date)
    add_meeting_events(events, db, start_date, end_date)
    add_clinic_schedule_events(
        events, db, start_date, end_date,
        show_off_schedule_ids=show_off_schedule_ids,
        conflict_keys=conflict_keys,
    )
    add_surgery_events(events, db, start_date, end_date, conflict_keys=conflict_keys)
    add_aprima_surgery_events(events, db, start_date, end_date)
    add_unavailable_events(events, db, start_date, end_date)

    for conflict in off_display["off_conflicts"]:
        events.append({
            "id": f"off-conflict-{conflict.surgeon_id}-{conflict.day.isoformat()}",
            "title": f"⚠ {conflict.surgeon_initials} OFF conflict",
            "start": conflict.day.isoformat(),
            "color": "#fecdd3",
            "textColor": "#9f1239",
            "extendedProps": {
                "type": "off_conflict",
                "surgeon_id": conflict.surgeon_id,
                "surgeon": conflict.surgeon_name,
                "message": conflict.message,
                "day_off_status": conflict.day_off_status,
                "sort_key": SORT_DAYOFF,
            },
        })
    return events
