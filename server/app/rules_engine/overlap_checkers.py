"""Overlap rule checker functions."""
from datetime import date, timedelta
from typing import Iterator, Optional

from sqlalchemy import or_
from sqlalchemy.orm import Session

from .checker_helpers import (
    case_range,
    exclude_entity as _exclude_entity,
    meeting_range,
    session_range,
    target_dates,
)
from .overlap_helpers import overlap_target, should_skip_time_overlap
from .registry import Conflict


def check_overlap_day_off(
    surgeon_id: int,
    start_date: date,
    end_date: date,
    db: Session,
    config: dict,
    exclude_entity: Optional[tuple[str, int]] = None,
    target_entity: Optional[dict] = None,
) -> Iterator[Conflict]:
    from ..models import DayOff
    target_start, target_end = target_dates(target_entity, start_date, end_date)
    q = db.query(DayOff).filter(
        DayOff.surgeon_id == surgeon_id,
        DayOff.start_date <= target_end,
        DayOff.end_date >= target_start,
        DayOff.status == "approved",
    )
    if exclude_entity and exclude_entity[0] == "day_off":
        q = q.filter(DayOff.id != exclude_entity[1])
    for d in q.all():
        for d_ in range((min(d.end_date, end_date) - max(d.start_date, start_date)).days + 1):
            day = max(d.start_date, start_date) + timedelta(days=d_)
            msg = f"Approved day off on {day.strftime('%b %-d')}"
            yield Conflict(
                rule_id="OVERLAP_DAY_OFF",
                surgeon_id=surgeon_id,
                date=day,
                message=msg,
                conflicting_entity_type="day_off",
                conflicting_entity_id=d.id,
            )


def check_overlap_call(
    surgeon_id: int,
    start_date: date,
    end_date: date,
    db: Session,
    config: dict,
    exclude_entity: Optional[tuple[str, int]] = None,
    target_entity: Optional[dict] = None,
) -> Iterator[Conflict]:
    from ..models import CallRotation
    target_start, target_end = target_dates(target_entity, start_date, end_date)
    for r in db.query(CallRotation).filter(
        CallRotation.surgeon_id == surgeon_id,
        CallRotation.date >= target_start,
        CallRotation.date <= target_end,
    ).all():
        if _exclude_entity(exclude_entity, "call_rotation", r.id):
            continue
        label = "on-call"
        yield Conflict(
            rule_id="OVERLAP_CALL",
            surgeon_id=surgeon_id,
            date=r.date,
            message=f"Assigned {label} on {r.date.strftime('%b %-d')}",
            conflicting_entity_type="call_rotation",
            conflicting_entity_id=r.id,
        )


def check_overlap_unavailable(
    surgeon_id: int,
    start_date: date,
    end_date: date,
    db: Session,
    config: dict,
    exclude_entity: Optional[tuple[str, int]] = None,
    target_entity: Optional[dict] = None,
) -> Iterator[Conflict]:
    from ..models import Availability
    target_start, target_end = target_dates(target_entity, start_date, end_date)
    for av in db.query(Availability).filter(
        Availability.surgeon_id == surgeon_id,
        Availability.date >= target_start,
        Availability.date <= target_end,
        Availability.is_available == False,
    ).all():
        yield Conflict(
            rule_id="OVERLAP_UNAVAILABLE",
            surgeon_id=surgeon_id,
            date=av.date,
            message=f"Marked unavailable on {av.date.strftime('%b %-d')}",
            conflicting_entity_type="availability",
            conflicting_entity_id=av.id,
        )


def check_overlap_clinic(
    surgeon_id: int,
    start_date: date,
    end_date: date,
    db: Session,
    config: dict,
    exclude_entity: Optional[tuple[str, int]] = None,
    target_entity: Optional[dict] = None,
) -> Iterator[Conflict]:
    from ..models import ClinicSchedule
    target = overlap_target(target_entity, start_date, end_date)
    for cs in db.query(ClinicSchedule).filter(
        ClinicSchedule.surgeon_id == surgeon_id,
        ClinicSchedule.date >= target.start,
        ClinicSchedule.date <= target.end,
    ).all():
        if _exclude_entity(exclude_entity, "clinic_schedule", cs.id):
            continue
        if should_skip_time_overlap(target, cs.date, session_range(cs.date, cs.session), {"clinic_schedule", "surgical_case", "meeting"}):
            continue
        loc_name = cs.location.name if cs.location else "Clinic"
        yield Conflict(
            rule_id="OVERLAP_CLINIC",
            surgeon_id=surgeon_id,
            date=cs.date,
            message=f"Clinic at {loc_name} on {cs.date.strftime('%b %-d')} ({cs.session})",
            conflicting_entity_type="clinic_schedule",
            conflicting_entity_id=cs.id,
        )


def check_overlap_surgery(
    surgeon_id: int,
    start_date: date,
    end_date: date,
    db: Session,
    config: dict,
    exclude_entity: Optional[tuple[str, int]] = None,
    target_entity: Optional[dict] = None,
) -> Iterator[Conflict]:
    from ..models import SurgicalCase
    target = overlap_target(target_entity, start_date, end_date)
    q = db.query(SurgicalCase).filter(
        SurgicalCase.surgeon_id == surgeon_id,
        SurgicalCase.date >= target.start,
        SurgicalCase.date <= target.end,
        SurgicalCase.status != "cancelled",
    )
    if exclude_entity and exclude_entity[0] == "surgical_case":
        q = q.filter(SurgicalCase.id != exclude_entity[1])
    for sc in q.all():
        if should_skip_time_overlap(target, sc.date, case_range(sc), {"surgical_case", "clinic_schedule", "meeting"}):
            continue
        yield Conflict(
            rule_id="OVERLAP_SURGERY",
            surgeon_id=surgeon_id,
            date=sc.date,
            message=f"Surgery on {sc.date.strftime('%b %-d')} ({sc.start_time.strftime('%-I:%M %p')} — {sc.patient_name or 'case'})",
            conflicting_entity_type="surgical_case",
            conflicting_entity_id=sc.id,
        )


def check_overlap_meeting(
    surgeon_id: int,
    start_date: date,
    end_date: date,
    db: Session,
    config: dict,
    exclude_entity: Optional[tuple[str, int]] = None,
    target_entity: Optional[dict] = None,
) -> Iterator[Conflict]:
    from ..models import Meeting, MeetingAttendee
    target = overlap_target(target_entity, start_date, end_date)
    meetings = (
        db.query(Meeting)
        .outerjoin(MeetingAttendee)
        .filter(
            Meeting.date >= target.start,
            Meeting.date <= target.end,
            or_(
                MeetingAttendee.surgeon_id == surgeon_id,
                ~Meeting.attendees.any(),
            ),
        )
        .distinct()
        .all()
    )
    for m in meetings:
        if _exclude_entity(exclude_entity, "meeting", m.id):
            continue
        if should_skip_time_overlap(target, m.date, meeting_range(m), {"meeting", "clinic_schedule", "surgical_case"}):
            continue
        time_str = m.start_time.strftime("%-I:%M %p") if m.start_time else "TBD"
        yield Conflict(
            rule_id="OVERLAP_MEETING",
            surgeon_id=surgeon_id,
            date=m.date,
            message=f"Meeting: {m.title} on {m.date.strftime('%b %-d')} at {time_str}",
            conflicting_entity_type="meeting",
            conflicting_entity_id=m.id,
        )


def check_clinic_group_day_off_capacity(
    surgeon_id: int,
    start_date: date,
    end_date: date,
    db: Session,
    config: dict,
    exclude_entity: Optional[tuple[str, int]] = None,
    target_entity: Optional[dict] = None,
) -> Iterator[Conflict]:
    if (target_entity or {}).get("type") != "day_off":
        return

    from ..models import Surgeon
    from ..scheduling_guardrails_service import clinic_group_day_off_findings

    surgeon = db.get(Surgeon, surgeon_id)
    exclude_dayoff_id = exclude_entity[1] if exclude_entity and exclude_entity[0] == "day_off" else None
    for finding in clinic_group_day_off_findings(db, surgeon, start_date, end_date, exclude_dayoff_id):
        yield Conflict(
            rule_id="CLINIC_GROUP_DAY_OFF_CAPACITY",
            surgeon_id=surgeon_id,
            date=finding.date,
            message=finding.message,
            severity="warning",
            conflicting_entity_type="clinic_group",
            conflicting_entity_id=finding.clinic_group_id,
        )
