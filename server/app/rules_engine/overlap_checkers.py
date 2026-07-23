"""Overlap rule checker functions."""
from datetime import date, datetime, time, timedelta
from typing import Iterator, Optional

from sqlalchemy import or_
from sqlalchemy.orm import Session, joinedload

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
    target = overlap_target(target_entity, start_date, end_date)
    target_start, target_end = target.start, target.end
    q = db.query(DayOff).filter(
        DayOff.surgeon_id == surgeon_id,
        DayOff.start_date <= target_end,
        DayOff.end_date >= target_start,
        DayOff.status.in_(["approved", "pending"]),
    )
    if exclude_entity and exclude_entity[0] == "day_off":
        q = q.filter(DayOff.id != exclude_entity[1])
    for d in q.all():
        # When the target itself is a day_off create/update, pending self-dups are
        # hard-rejected elsewhere; still surface approved/pending overlaps for other targets.
        if (target_entity or {}).get("type") == "day_off" and d.status == "pending":
            continue
        for d_ in range((min(d.end_date, target_end) - max(d.start_date, target_start)).days + 1):
            day = max(d.start_date, target_start) + timedelta(days=d_)
            other_range = _day_off_row_range(d, day)
            if should_skip_time_overlap(target, day, other_range, {"day_off", "clinic_schedule", "surgical_case", "meeting", "or_block", "call_rotation"}):
                continue
            status_label = "Approved" if d.status == "approved" else "Pending"
            msg = f"{status_label} day off on {day.strftime('%b %-d')}"
            yield Conflict(
                rule_id="OVERLAP_DAY_OFF",
                surgeon_id=surgeon_id,
                date=day,
                message=msg,
                conflicting_entity_type="day_off",
                conflicting_entity_id=d.id,
            )


def _day_off_row_range(row, day: date) -> tuple[datetime, datetime]:
    from ..native_dayoff_support import segment_for_date
    from .checker_helpers import _coerce_time

    segment = segment_for_date(row, day)
    if segment is None:
        start_dt = datetime.combine(day, time(0, 0))
        return start_dt, start_dt + timedelta(days=1)
    if segment.get("isFullDay", True):
        start_dt = datetime.combine(day, time(0, 0))
        return start_dt, start_dt + timedelta(days=1)
    start_t = _coerce_time(segment.get("start")) or row.start_time
    end_t = _coerce_time(segment.get("end")) or row.end_time
    if not start_t or not end_t:
        start_dt = datetime.combine(day, time(0, 0))
        return start_dt, start_dt + timedelta(days=1)
    return datetime.combine(day, start_t), datetime.combine(day, end_t)


def _call_group_location_ids(db: Session, call_group_id: int | None) -> set[int]:
    if not call_group_id:
        return set()
    from ..models import CallGroupLocation

    rows = (
        db.query(CallGroupLocation.location_id)
        .filter(CallGroupLocation.call_group_id == call_group_id)
        .all()
    )
    return {row[0] for row in rows if row[0] is not None}


def _surgery_at_on_call_facility(
    *,
    target_entity: Optional[dict],
    covered_location_ids: set[int],
) -> bool:
    """True when OR/surgery is at a hospital covered by this call group.

    On-call + operating at the same Advent campus is expected, not a conflict.
    """
    if not target_entity or not covered_location_ids:
        return False
    target_type = (target_entity.get("type") or "").strip().lower()
    if target_type not in {"or_block", "surgical_case"}:
        return False
    location_id = target_entity.get("location_id")
    try:
        location_id = int(location_id) if location_id is not None else None
    except (TypeError, ValueError):
        return False
    return location_id in covered_location_ids


def check_overlap_call(
    surgeon_id: int,
    start_date: date,
    end_date: date,
    db: Session,
    config: dict,
    exclude_entity: Optional[tuple[str, int]] = None,
    target_entity: Optional[dict] = None,
) -> Iterator[Conflict]:
    """Effective on-call: original rotation unless covered; covering surgeon is on-call.

    Surgery / Block OR at a hospital in the call group is allowed (same-facility call).
    """
    from ..models import CallCoverage, CallRotation

    target = overlap_target(target_entity, start_date, end_date)
    target_start, target_end = target.start, target.end

    rotations = (
        db.query(CallRotation)
        .options(joinedload(CallRotation.coverages), joinedload(CallRotation.call_group))
        .filter(
            CallRotation.date >= target_start,
            CallRotation.date <= target_end,
        )
        .all()
    )
    for r in rotations:
        if _exclude_entity(exclude_entity, "call_rotation", r.id):
            continue
        active = next((c for c in (r.coverages or []) if c.status == "active"), None)
        effective_id = active.covering_surgeon_id if active else r.surgeon_id
        if effective_id != surgeon_id:
            continue
        # Full-day call commitment unless target is a partial day-off that ends before overnight call
        call_range = (
            datetime.combine(r.date, time(0, 0)),
            datetime.combine(r.date, time(0, 0)) + timedelta(days=1),
        )
        if should_skip_time_overlap(
            target,
            r.date,
            call_range,
            {"day_off", "clinic_schedule", "surgical_case", "meeting", "or_block", "call_rotation"},
        ):
            continue
        covered_ids = _call_group_location_ids(db, r.call_group_id)
        if _surgery_at_on_call_facility(
            target_entity=target_entity,
            covered_location_ids=covered_ids,
        ):
            continue
        group = r.call_group.name if r.call_group else "call"
        if active and active.covering_surgeon_id == surgeon_id:
            msg = f"Covering on-call ({group}) on {r.date.strftime('%b %-d')}"
            entity_type = "call_coverage"
            entity_id = active.id
        else:
            msg = f"Assigned on-call ({group}) on {r.date.strftime('%b %-d')}"
            entity_type = "call_rotation"
            entity_id = r.id
        yield Conflict(
            rule_id="OVERLAP_CALL",
            surgeon_id=surgeon_id,
            date=r.date,
            message=msg,
            conflicting_entity_type=entity_type,
            conflicting_entity_id=entity_id,
        )

    # Covering surgeon may also have coverage rows whose rotation wasn't loaded above
    # (already covered via join). Extra: coverages where covering_surgeon_id matches
    # but rotation.surgeon_id differs — already handled. Done.


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
    target = overlap_target(target_entity, start_date, end_date)
    for av in db.query(Availability).filter(
        Availability.surgeon_id == surgeon_id,
        Availability.date >= target.start,
        Availability.date <= target.end,
        Availability.is_available == False,  # noqa: E712
    ).all():
        if av.start_time and av.end_time:
            row_range = (
                datetime.combine(av.date, av.start_time),
                datetime.combine(av.date, av.end_time),
            )
        else:
            start_dt = datetime.combine(av.date, time(0, 0))
            row_range = (start_dt, start_dt + timedelta(days=1))
        if should_skip_time_overlap(
            target,
            av.date,
            row_range,
            {"day_off", "clinic_schedule", "surgical_case", "meeting", "or_block", "call_rotation"},
        ):
            continue
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
    from sqlalchemy.orm import joinedload

    target = overlap_target(target_entity, start_date, end_date)
    for cs in (
        db.query(ClinicSchedule)
        .options(joinedload(ClinicSchedule.location))
        .filter(
            ClinicSchedule.surgeon_id == surgeon_id,
            ClinicSchedule.date >= target.start,
            ClinicSchedule.date <= target.end,
        )
        .all()
    ):
        if _exclude_entity(exclude_entity, "clinic_schedule", cs.id):
            continue
        # "Off" clinic markers are not a scheduled clinic commitment.
        if (cs.assignment_type or "").lower() in {"off", "__off__", "day_off"}:
            continue
        # Clinic/OR grid stores OR days as hospital locations on ClinicSchedule —
        # that is Block OR capacity, not a clinic conflict.
        loc = cs.location
        if loc:
            abbr = (loc.abbreviation or "").upper()
            ltype = (loc.location_type or "").lower()
            if abbr.endswith("-OR") or ltype in {"hospital", "or"}:
                continue
        if should_skip_time_overlap(
            target,
            cs.date,
            session_range(cs.date, cs.session),
            {"clinic_schedule", "surgical_case", "meeting", "day_off", "or_block", "call_rotation"},
        ):
            continue
        loc_name = loc.name if loc else "Clinic"
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
        # Cases under this Block OR are inventory under the block — not a conflict.
        if target.kind == "or_block":
            block_id = (target.entity or {}).get("or_block_instance_id") or (target.entity or {}).get("block_id")
            if block_id and sc.or_block_instance_id and int(block_id) == int(sc.or_block_instance_id):
                continue
            loc_id = (target.entity or {}).get("location_id")
            if loc_id and sc.location_id and int(loc_id) == int(sc.location_id):
                continue
        if should_skip_time_overlap(
            target,
            sc.date,
            case_range(sc),
            {"surgical_case", "clinic_schedule", "meeting", "day_off", "or_block", "call_rotation"},
        ):
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
            MeetingAttendee.surgeon_id == surgeon_id,
        )
        .distinct()
        .all()
    )
    for m in meetings:
        if _exclude_entity(exclude_entity, "meeting", m.id):
            continue
        if should_skip_time_overlap(
            target,
            m.date,
            meeting_range(m),
            {"meeting", "clinic_schedule", "surgical_case", "day_off", "or_block", "call_rotation"},
        ):
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


def check_overlap_or_block(
    surgeon_id: int,
    start_date: date,
    end_date: date,
    db: Session,
    config: dict,
    exclude_entity: Optional[tuple[str, int]] = None,
    target_entity: Optional[dict] = None,
) -> Iterator[Conflict]:
    from ..models import ORBlockAssignment, ORBlockInstance, Location

    target = overlap_target(target_entity, start_date, end_date)
    rows = (
        db.query(ORBlockAssignment, ORBlockInstance)
        .join(ORBlockInstance, ORBlockAssignment.block_instance_id == ORBlockInstance.id)
        .options(joinedload(ORBlockInstance.location))
        .filter(
            ORBlockAssignment.surgeon_id == surgeon_id,
            ORBlockInstance.date >= target.start,
            ORBlockInstance.date <= target.end,
            ORBlockInstance.status != "released",
        )
        .all()
    )
    for assignment, instance in rows:
        if _exclude_entity(exclude_entity, "or_block_assignment", assignment.id):
            continue
        if _exclude_entity(exclude_entity, "or_block", instance.id):
            continue
        # Surgical cases are expected to live inside Block OR capacity.
        if target.kind == "surgical_case":
            target_block_id = (target.entity or {}).get("or_block_instance_id")
            target_loc = (target.entity or {}).get("location_id")
            if target_block_id and int(target_block_id) == instance.id:
                continue
            if not target_loc or target_loc == instance.location_id:
                continue
        # Assigning/evaluating this same block is not a conflict with itself.
        if target.kind == "or_block":
            target_block_id = (target.entity or {}).get("or_block_instance_id") or (target.entity or {}).get("block_id")
            if target_block_id and int(target_block_id) == instance.id:
                continue
        start_t = assignment.start_time or instance.start_time or time(7, 0)
        end_t = instance.end_time or time(17, 0)
        row_range = (
            datetime.combine(instance.date, start_t),
            datetime.combine(instance.date, end_t),
        )
        if should_skip_time_overlap(
            target,
            instance.date,
            row_range,
            {"day_off", "clinic_schedule", "surgical_case", "meeting", "or_block", "call_rotation"},
        ):
            continue
        loc = instance.location.name if instance.location else "OR"
        yield Conflict(
            rule_id="OVERLAP_OR_BLOCK",
            surgeon_id=surgeon_id,
            date=instance.date,
            message=f"OR block at {loc} on {instance.date.strftime('%b %-d')} from {start_t.strftime('%-I:%M %p')}",
            conflicting_entity_type="or_block",
            conflicting_entity_id=instance.id,
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
