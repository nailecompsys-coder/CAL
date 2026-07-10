"""Block OR scheduling services.

Block OR is practice capacity inventory. It is separate from ClinicSchedule rows
because open block time may exist before any surgeon is assigned.
"""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone

from sqlalchemy import or_
from sqlalchemy.orm import Session, joinedload

from .conflicts import check_conflicts_structured
from .models import (
    AdminUser,
    Location,
    ORBlockAuditEvent,
    ORBlockAssignment,
    ORBlockInstance,
    ORBlockSeries,
    NativePushToken,
    ScheduleChangeEvent,
    Surgeon,
    SurgicalCase,
)
from .push import send_native_push_to_surgeon
from .email_service import send_email
from .scheduling_guardrails_service import scheduler_safe_warning
from .surgeon_visibility import surgeon_is_visible


SESSION_DEFAULTS = {
    "am": (time(7, 0), time(12, 0)),
    "pm": (time(12, 0), time(17, 0)),
    "both": (time(7, 0), time(17, 0)),
    "custom": (time(7, 0), time(12, 0)),
}

ACTIVE_BLOCK_STATUSES = {"open", "assigned"}
OPEN_BLOCK_STATUSES = {"open"}
NON_DUPLICATE_BLOCKING_STATUSES = {"open", "assigned"}


@dataclass(frozen=True)
class BlockORCreateInput:
    name: str
    start_date: date
    end_date: date
    weekdays: list[int]
    location_ids: list[int]
    session: str
    start_time: time
    end_time: time
    recurrence: str = "weekly"
    owner_type: str = "practice"
    owner_surgeon_id: int | None = None
    release_policy_days: int = 3
    notes: str | None = None


def parse_hhmm(value: str, fallback: time | None = None) -> time:
    if not value:
        if fallback is None:
            raise ValueError("Time is required")
        return fallback
    return datetime.strptime(value, "%H:%M").time()


def normalize_session(session: str) -> str:
    return session if session in SESSION_DEFAULTS else "custom"


def session_default_times(session: str) -> tuple[time, time]:
    return SESSION_DEFAULTS.get(normalize_session(session), SESSION_DEFAULTS["custom"])


def daterange(start_date: date, end_date: date):
    current = start_date
    while current <= end_date:
        yield current
        current += timedelta(days=1)


def _block_release_deadline(block_date: date, release_policy_days: int | None) -> datetime:
    return datetime.combine(block_date, time(7, 0)) - timedelta(days=int(release_policy_days or 3))


def block_times_overlap(start_a: time, end_a: time, start_b: time, end_b: time) -> bool:
    return start_a < end_b and start_b < end_a


def overlapping_or_blocks(
    db: Session,
    *,
    block_date: date,
    location_id: int,
    start_time: time,
    end_time: time,
    exclude_block_id: int | None = None,
) -> list[ORBlockInstance]:
    q = db.query(ORBlockInstance).filter(
        ORBlockInstance.date == block_date,
        ORBlockInstance.location_id == location_id,
        ORBlockInstance.status.in_(NON_DUPLICATE_BLOCKING_STATUSES),
        ORBlockInstance.start_time < end_time,
        ORBlockInstance.end_time > start_time,
    )
    if exclude_block_id is not None:
        q = q.filter(ORBlockInstance.id != exclude_block_id)
    return q.order_by(ORBlockInstance.start_time, ORBlockInstance.id).all()


def duplicate_block_messages(db: Session, payload: BlockORCreateInput) -> list[str]:
    weekdays = set(payload.weekdays or [payload.start_date.weekday()])
    location_ids = list(dict.fromkeys(payload.location_ids))
    messages = []
    seen = set()
    for block_date in daterange(payload.start_date, payload.end_date):
        if payload.recurrence == "once" and block_date != payload.start_date:
            continue
        if payload.recurrence != "once" and block_date.weekday() not in weekdays:
            continue
        for location_id in location_ids:
            overlaps = overlapping_or_blocks(
                db,
                block_date=block_date,
                location_id=location_id,
                start_time=payload.start_time,
                end_time=payload.end_time,
            )
            for overlap in overlaps:
                location = overlap.location.name if overlap.location else f"location {location_id}"
                key = (block_date, location_id, overlap.start_time, overlap.end_time, overlap.status)
                if key in seen:
                    continue
                seen.add(key)
                messages.append(
                    f"{location} already has {overlap.status.replace('_', ' ')} block time "
                    f"{block_date.strftime('%a %-m/%-d')} {overlap.start_time.strftime('%H:%M')}-{overlap.end_time.strftime('%H:%M')}."
                )
    return messages


def audit_block(db: Session, block_id: int, admin_id: int | None, event_type: str, detail: dict | str | None = None) -> None:
    if isinstance(detail, dict):
        detail_text = json.dumps(detail, default=str)
    else:
        detail_text = detail
    db.add(ORBlockAuditEvent(
        block_instance_id=block_id,
        admin_user_id=admin_id,
        event_type=event_type,
        detail=detail_text,
    ))


def log_schedule_change(
    db: Session,
    *,
    event_type: str,
    title: str,
    body: str = "",
    surgeon_id: int | None = None,
    admin_user_id: int | None = None,
    event_date: date | None = None,
    payload: dict | None = None,
) -> None:
    db.add(ScheduleChangeEvent(
        event_type=event_type,
        surgeon_id=surgeon_id,
        admin_user_id=admin_user_id,
        date=event_date,
        title=title,
        body=body,
        payload=json.dumps(payload or {}, default=str),
    ))


def create_or_blocks(db: Session, payload: BlockORCreateInput, admin_id: int | None = None) -> dict:
    if payload.start_date > payload.end_date:
        raise ValueError("Start date must be before end date")
    if payload.start_time >= payload.end_time:
        raise ValueError("Start time must be before end time")
    weekdays = set(payload.weekdays or [payload.start_date.weekday()])
    location_ids = list(dict.fromkeys(payload.location_ids))
    if not location_ids:
        raise ValueError("At least one OR location is required")
    duplicates = duplicate_block_messages(db, payload)
    if duplicates:
        raise ValueError("Duplicate Block OR time: " + " ".join(duplicates[:4]))

    series = ORBlockSeries(
        name=payload.name.strip() or "Open Block",
        recurrence=payload.recurrence if payload.recurrence in {"weekly", "once"} else "weekly",
        weekday=next(iter(sorted(weekdays))) if len(weekdays) == 1 else None,
        start_date=payload.start_date,
        end_date=payload.end_date,
        session=normalize_session(payload.session),
        start_time=payload.start_time,
        end_time=payload.end_time,
        owner_type=payload.owner_type if payload.owner_type in {"practice", "surgeon"} else "practice",
        owner_surgeon_id=payload.owner_surgeon_id,
        release_policy_days=payload.release_policy_days,
        notes=(payload.notes or "").strip() or None,
        created_by_admin_id=admin_id,
    )
    db.add(series)
    db.flush()

    created: list[ORBlockInstance] = []
    for block_date in daterange(payload.start_date, payload.end_date):
        if payload.recurrence == "once" and block_date != payload.start_date:
            continue
        if payload.recurrence != "once" and block_date.weekday() not in weekdays:
            continue
        for location_id in location_ids:
            instance = ORBlockInstance(
                series_id=series.id,
                location_id=location_id,
                date=block_date,
                session=series.session,
                start_time=payload.start_time,
                end_time=payload.end_time,
                status="open",
                release_deadline=_block_release_deadline(block_date, payload.release_policy_days),
                notes=series.notes,
            )
            db.add(instance)
            db.flush()
            audit_block(db, instance.id, admin_id, "created", {
                "seriesId": series.id,
                "locationId": location_id,
                "date": block_date.isoformat(),
            })
            created.append(instance)
    db.commit()
    return {"series_id": series.id, "created": len(created), "instance_ids": [row.id for row in created]}


def update_or_block_instance(
    db: Session,
    block_id: int,
    *,
    location_id: int | None = None,
    session: str | None = None,
    start_time: time | None = None,
    end_time: time | None = None,
    notes: str | None = None,
    admin_id: int | None = None,
) -> ORBlockInstance:
    block = (
        db.query(ORBlockInstance)
        .options(
            joinedload(ORBlockInstance.location),
            joinedload(ORBlockInstance.assignments),
        )
        .filter(ORBlockInstance.id == block_id)
        .first()
    )
    if not block:
        raise ValueError("Block OR not found")

    new_location_id = int(location_id) if location_id is not None else block.location_id
    new_session = normalize_session(session) if session is not None else block.session
    new_start = start_time if start_time is not None else block.start_time
    new_end = end_time if end_time is not None else block.end_time
    if new_start >= new_end:
        raise ValueError("Start time must be before end time")

    location = db.get(Location, new_location_id)
    if not location or not location.is_active:
        raise ValueError("OR location is required")
    if (location.location_type or "clinic") != "hospital":
        raise ValueError("Block OR locations must be hospitals")

    overlaps = overlapping_or_blocks(
        db,
        block_date=block.date,
        location_id=new_location_id,
        start_time=new_start,
        end_time=new_end,
        exclude_block_id=block.id,
    )
    if overlaps:
        other = overlaps[0]
        loc_label = other.location.name if other.location else "location"
        raise ValueError(
            f"Duplicate Block OR time: {loc_label} already has "
            f"{other.status.replace('_', ' ')} block time "
            f"{block.date.strftime('%a %-m/%-d')} "
            f"{other.start_time.strftime('%H:%M')}-{other.end_time.strftime('%H:%M')}."
        )

    for assignment in list(block.assignments or []):
        if assignment.start_time < new_start or assignment.start_time >= new_end:
            raise ValueError(
                f"Assigned start {assignment.start_time.strftime('%H:%M')} falls outside the new block window. "
                "Clear the assignment in the mobile app first, or keep a window that includes it."
            )

    before = {
        "locationId": block.location_id,
        "session": block.session,
        "start": block.start_time.strftime("%H:%M"),
        "end": block.end_time.strftime("%H:%M"),
        "notes": block.notes or "",
    }
    block.location_id = new_location_id
    block.session = new_session
    block.start_time = new_start
    block.end_time = new_end
    if notes is not None:
        block.notes = notes.strip() or None
    audit_block(db, block.id, admin_id, "updated", {
        "before": before,
        "after": {
            "locationId": block.location_id,
            "session": block.session,
            "start": block.start_time.strftime("%H:%M"),
            "end": block.end_time.strftime("%H:%M"),
            "notes": block.notes or "",
        },
    })
    log_schedule_change(
        db,
        event_type="or_block_updated",
        title=f"Block OR updated · {location.abbreviation or location.name}",
        body=(
            f"{block.date.isoformat()} "
            f"{block.start_time.strftime('%H:%M')}-{block.end_time.strftime('%H:%M')}"
        ),
        admin_user_id=admin_id,
        event_date=block.date,
        payload={"blockId": block.id, "locationId": block.location_id},
    )
    db.commit()
    db.refresh(block)
    return block


def delete_or_block_instance(
    db: Session,
    block_id: int,
    *,
    admin_id: int | None = None,
) -> None:
    block = (
        db.query(ORBlockInstance)
        .options(
            joinedload(ORBlockInstance.location),
            joinedload(ORBlockInstance.assignments),
            joinedload(ORBlockInstance.cases),
        )
        .filter(ORBlockInstance.id == block_id)
        .first()
    )
    if not block:
        raise ValueError("Block OR not found")

    has_assignment = bool(block.assignments) or bool(block.assigned_surgeon_id)
    if has_assignment or (block.status or "") == "assigned":
        raise ValueError(
            "This block has a surgeon assignment. Clear the assignment in the mobile app first, then delete."
        )
    active_cases = [case for case in (block.cases or []) if (case.status or "") != "cancelled"]
    if active_cases:
        raise ValueError("This block still has linked surgical cases. Move or cancel those cases first.")

    loc_label = block.location.abbreviation if block.location and block.location.abbreviation else (
        block.location.name if block.location else "OR"
    )
    # ScheduleChangeEvent keeps the deletion history (no FK to the instance).
    # Do NOT write ORBlockAuditEvent here — that row would block the DELETE.
    log_schedule_change(
        db,
        event_type="or_block_deleted",
        title=f"Block OR removed · {loc_label}",
        body=(
            f"{block.date.isoformat()} "
            f"{block.start_time.strftime('%H:%M')}-{block.end_time.strftime('%H:%M')}"
        ),
        admin_user_id=admin_id,
        event_date=block.date,
        payload={
            "blockId": block.id,
            "locationId": block.location_id,
            "start": block.start_time.strftime("%H:%M"),
            "end": block.end_time.strftime("%H:%M"),
            "status": block.status,
        },
    )
    # Detach leftover case links. Audit FK has no ON DELETE CASCADE at DB level,
    # so clear those rows before removing the instance.
    for case in list(block.cases or []):
        case.or_block_instance_id = None
    db.query(ORBlockAuditEvent).filter(ORBlockAuditEvent.block_instance_id == block.id).delete(
        synchronize_session=False
    )
    db.expire(block, ["audit_events"])
    db.delete(block)
    db.commit()


def block_instances_for_range(db: Session, start_date: date, end_date: date) -> list[ORBlockInstance]:
    return (
        db.query(ORBlockInstance)
        .filter(ORBlockInstance.date >= start_date, ORBlockInstance.date <= end_date)
        .options(
            joinedload(ORBlockInstance.location),
            joinedload(ORBlockInstance.assigned_surgeon),
            joinedload(ORBlockInstance.assignments).joinedload(ORBlockAssignment.surgeon),
            joinedload(ORBlockInstance.cases),
        )
        .order_by(ORBlockInstance.date, ORBlockInstance.start_time, ORBlockInstance.location_id)
        .all()
    )


def open_blocks_by_day(db: Session, start_date: date, end_date: date) -> dict[date, list[ORBlockInstance]]:
    out: dict[date, list[ORBlockInstance]] = defaultdict(list)
    for block in block_instances_for_range(db, start_date, end_date):
        if block.status in OPEN_BLOCK_STATUSES:
            out[block.date].append(block)
    return out


def _safe_surgeon_label(surgeon: Surgeon | None) -> str:
    if not surgeon:
        return "Open"
    return surgeon.initials or surgeon.full_name


def _assignment_payload(block: ORBlockInstance, assignment: ORBlockAssignment) -> dict:
    location_label = block.location.abbreviation if block.location and block.location.abbreviation else (block.location.name if block.location else "OR")
    cases = assignment.case_count or 0
    case_word = "Case" if cases == 1 else "Cases"
    initials = assignment.surgeon.initials if assignment.surgeon else ""
    label = f"{location_label} - {assignment.start_time.strftime('%H:%M')} - {cases} {case_word}"
    if initials:
        label = f"{label} {initials}"
    return {
        "id": assignment.id,
        "surgeonId": assignment.surgeon_id,
        "surgeon": assignment.surgeon.full_name if assignment.surgeon else "",
        "surgeonInitials": initials,
        "start": assignment.start_time.strftime("%H:%M"),
        "caseCount": cases,
        "note": assignment.note or "",
        "label": label,
    }


def block_assignment_payloads(block: ORBlockInstance) -> list[dict]:
    assignments = sorted(
        list(block.assignments or []),
        key=lambda row: (row.start_time, row.id or 0),
    )
    if assignments:
        return [_assignment_payload(block, row) for row in assignments]
    if not block.assigned_surgeon_id:
        return []
    legacy = ORBlockAssignment(
        id=0,
        block_instance_id=block.id,
        surgeon_id=block.assigned_surgeon_id,
        start_time=block.assigned_start_time or block.start_time,
        case_count=block.assigned_case_count or 0,
        note=block.assignment_note,
    )
    legacy.surgeon = block.assigned_surgeon
    return [_assignment_payload(block, legacy)]


def serialize_block_instance(block: ORBlockInstance) -> dict:
    assignments = block_assignment_payloads(block)
    first_assignment = assignments[0] if assignments else None
    assigned_start = parse_hhmm(first_assignment["start"], block.start_time) if first_assignment else (block.assigned_start_time or block.start_time)
    total_cases = sum(row["caseCount"] for row in assignments) if assignments else (block.assigned_case_count or 0)
    assignment_label = first_assignment["label"] if first_assignment else ""
    status = "assigned" if assignments else (block.status or "open")
    return {
        "id": block.id,
        "date": block.date.isoformat(),
        "session": block.session or "custom",
        "start": block.start_time.strftime("%H:%M"),
        "end": block.end_time.strftime("%H:%M"),
        "status": status,
        "locationId": block.location_id,
        "location": block.location.name if block.location else "",
        "locationAbbreviation": block.location.abbreviation if block.location else "",
        "surgeonId": first_assignment["surgeonId"] if first_assignment else block.assigned_surgeon_id,
        "surgeon": first_assignment["surgeon"] if first_assignment else (block.assigned_surgeon.full_name if block.assigned_surgeon else None),
        "surgeonInitials": first_assignment["surgeonInitials"] if first_assignment else _safe_surgeon_label(block.assigned_surgeon),
        "assignedStart": assigned_start.strftime("%H:%M") if assigned_start else None,
        "caseCount": total_cases,
        "assignmentNote": block.assignment_note or "",
        "assignmentLabel": assignment_label,
        "assignments": assignments,
        "notes": block.notes or "",
    }


def block_workspace(db: Session, start_date: date, end_date: date) -> dict:
    locations = (
        db.query(Location)
        .filter(Location.is_active == True, Location.location_type == "hospital")  # noqa: E712
        .order_by(Location.name)
        .all()
    )
    blocks = block_instances_for_range(db, start_date, end_date)
    blocks_by_location: dict[int, dict[date, list[dict]]] = defaultdict(lambda: defaultdict(list))
    for block in blocks:
        blocks_by_location[block.location_id][block.date].append(serialize_block_instance(block))
    return {
        "locations": locations,
        "blocks_by_location": blocks_by_location,
        "blocks": blocks,
    }


def block_assignment_warnings(
    db: Session,
    block: ORBlockInstance,
    surgeon_id: int,
    start_time: time | None = None,
    end_time: time | None = None,
) -> list[str]:
    start = start_time or block.start_time
    end = end_time or block.end_time
    warnings: list[str] = []
    if start < block.start_time or end > block.end_time:
        warnings.append(
            f"Outside block time {block.start_time.strftime('%H:%M')}-{block.end_time.strftime('%H:%M')}."
        )

    conflicts = check_conflicts_structured(
        surgeon_id,
        block.date,
        block.date,
        db,
        target_entity={
            "type": "surgical_case",
            "date": block.date,
            "start_time": start,
            "end_time": end,
        },
    )
    for conflict in conflicts:
        label = {
            "OVERLAP_SURGERY": "Overlaps another surgical case",
            "OVERLAP_CLINIC": "Overlaps clinic schedule",
            "OVERLAP_DAY_OFF": "Overlaps approved day off",
            "OVERLAP_MEETING": "Overlaps assigned meeting",
            "OVERLAP_UNAVAILABLE": "Overlaps unavailable time",
            "OVERLAP_CALL": "Surgeon is on call",
        }.get(conflict.rule_id, "Schedule warning")
        warnings.append(scheduler_safe_warning(f"{label}: {conflict.message}"))
    assigned_blocks = db.query(ORBlockAssignment, ORBlockInstance).join(
        ORBlockInstance,
        ORBlockAssignment.block_instance_id == ORBlockInstance.id,
    ).filter(
        ORBlockAssignment.surgeon_id == surgeon_id,
        ORBlockInstance.date == block.date,
        ORBlockInstance.id != block.id,
        ORBlockInstance.start_time < end,
        ORBlockInstance.end_time > start,
    ).all()
    for _assignment, assigned in assigned_blocks:
        if assigned.location_id == block.location_id:
            continue
        location = assigned.location.abbreviation if assigned.location and assigned.location.abbreviation else (assigned.location.name if assigned.location else "OR")
        warnings.append(
            f"Already assigned Block OR: {location} {assigned.start_time.strftime('%H:%M')}-{assigned.end_time.strftime('%H:%M')}"
        )
    legacy_assigned_blocks = db.query(ORBlockInstance).filter(
        ORBlockInstance.assigned_surgeon_id == surgeon_id,
        ORBlockInstance.date == block.date,
        ORBlockInstance.status == "assigned",
        ORBlockInstance.id != block.id,
        ORBlockInstance.start_time < end,
        ORBlockInstance.end_time > start,
    ).all()
    for assigned in legacy_assigned_blocks:
        if assigned.assignments or assigned.location_id == block.location_id:
            continue
        location = assigned.location.abbreviation if assigned.location and assigned.location.abbreviation else (assigned.location.name if assigned.location else "OR")
        warnings.append(
            f"Already assigned Block OR: {location} {assigned.start_time.strftime('%H:%M')}-{assigned.end_time.strftime('%H:%M')}"
        )
    deduped = []
    for warning in warnings:
        if warning and warning not in deduped:
            deduped.append(warning)
    return deduped


def _availability_summary(block: ORBlockInstance, warnings: list[str]) -> str:
    if not warnings:
        return f"Available {block.start_time.strftime('%H:%M')}-{block.end_time.strftime('%H:%M')}"
    primary = warnings[0]
    if primary.startswith("Already assigned Block OR"):
        return "Already assigned Block OR"
    if primary.startswith("Overlaps clinic schedule"):
        if block.session == "am":
            return "AM Clinic"
        if block.session == "pm":
            return "PM Clinic"
        return "Clinic"
    if primary.startswith("Overlaps approved day off"):
        return f"Day Off {block.date.strftime('%b %-d')}"
    if primary.startswith("Overlaps unavailable time"):
        return "Unavailable"
    if primary.startswith("Overlaps assigned meeting"):
        return "Meeting"
    if primary.startswith("Surgeon is on call"):
        return "On Call"
    return "Not Available"


def assign_block(
    db: Session,
    block_id: int,
    surgeon_id: int,
    admin_id: int | None = None,
    assigned_start_time: time | None = None,
    case_count: int | None = None,
    assignment_note: str | None = None,
) -> tuple[ORBlockInstance, list[str]]:
    block = db.get(ORBlockInstance, block_id)
    surgeon = db.get(Surgeon, surgeon_id)
    if not block:
        raise ValueError("Block not found")
    if not surgeon or not surgeon_is_visible(surgeon):
        raise ValueError("Surgeon not found")
    assigned_start = assigned_start_time or block.start_time
    duplicate = (
        db.query(ORBlockAssignment)
        .filter(
            ORBlockAssignment.block_instance_id == block.id,
            ORBlockAssignment.surgeon_id == surgeon_id,
            ORBlockAssignment.start_time == assigned_start,
        )
        .first()
    )
    if duplicate:
        raise ValueError("That surgeon is already assigned at this start time")
    warnings = block_assignment_warnings(db, block, surgeon_id, assigned_start, block.end_time)
    assignment = ORBlockAssignment(
        block_instance_id=block.id,
        surgeon_id=surgeon_id,
        assigned_by_admin_id=admin_id,
        start_time=assigned_start,
        case_count=max(1, int(case_count or 1)),
        note=(assignment_note or "").strip() or None,
    )
    db.add(assignment)
    if not block.assigned_surgeon_id:
        block.assigned_surgeon_id = surgeon_id
        block.assigned_by_admin_id = admin_id
        block.assigned_at = datetime.now(timezone.utc)
        block.assigned_start_time = assigned_start
        block.assigned_case_count = assignment.case_count
        block.assignment_note = assignment.note
    block.status = "assigned"
    db.flush()
    db.refresh(block)
    label = _assignment_payload(block, assignment)["label"]
    audit_block(db, block.id, admin_id, "assigned", {
        "surgeonId": surgeon_id,
        "assignedStart": assigned_start.strftime("%H:%M"),
        "caseCount": assignment.case_count,
        "assignmentId": assignment.id,
        "warnings": warnings,
    })
    log_schedule_change(
        db,
        event_type="block_or_assigned",
        surgeon_id=surgeon_id,
        admin_user_id=admin_id,
        event_date=block.date,
        title="Block OR assigned",
        body=label,
        payload={"blockId": block.id, "assignmentId": assignment.id, "warnings": warnings},
    )
    db.commit()
    db.refresh(block)
    db.expire(block, ["assignments"])
    send_native_push_to_surgeon(
        surgeon_id,
        "Block OR updated",
        label,
        db,
        {"kind": "block_or", "blockId": block.id, "date": block.date.isoformat()},
    )
    return block, warnings


def update_block_assignment(
    db: Session,
    block_id: int,
    assignment_id: int,
    surgeon_id: int,
    admin_id: int | None = None,
    assigned_start_time: time | None = None,
    case_count: int | None = None,
    assignment_note: str | None = None,
) -> tuple[ORBlockInstance, list[str]]:
    block = (
        db.query(ORBlockInstance)
        .options(joinedload(ORBlockInstance.assignments).joinedload(ORBlockAssignment.surgeon))
        .filter(ORBlockInstance.id == block_id)
        .first()
    )
    if not block:
        raise ValueError("Block not found")
    assignment = next((row for row in (block.assignments or []) if row.id == assignment_id), None)
    if not assignment:
        raise ValueError("Assignment not found")
    surgeon = db.get(Surgeon, surgeon_id)
    if not surgeon or not surgeon_is_visible(surgeon):
        raise ValueError("Surgeon not found")

    assigned_start = assigned_start_time or assignment.start_time
    duplicate = (
        db.query(ORBlockAssignment)
        .filter(
            ORBlockAssignment.block_instance_id == block.id,
            ORBlockAssignment.surgeon_id == surgeon_id,
            ORBlockAssignment.start_time == assigned_start,
            ORBlockAssignment.id != assignment_id,
        )
        .first()
    )
    if duplicate:
        raise ValueError("That surgeon is already assigned at this start time")

    previous_surgeon_id = assignment.surgeon_id
    warnings = block_assignment_warnings(db, block, surgeon_id, assigned_start, block.end_time)
    assignment.surgeon_id = surgeon_id
    assignment.assigned_by_admin_id = admin_id
    assignment.start_time = assigned_start
    assignment.case_count = max(1, int(case_count if case_count is not None else assignment.case_count or 1))
    assignment.note = (assignment_note or "").strip() or None
    _sync_legacy_assignment_fields(db, block)
    db.flush()
    db.refresh(assignment)
    label = _assignment_payload(block, assignment)["label"]
    audit_block(db, block.id, admin_id, "assignment_updated", {
        "assignmentId": assignment.id,
        "surgeonId": surgeon_id,
        "previousSurgeonId": previous_surgeon_id,
        "assignedStart": assigned_start.strftime("%H:%M"),
        "caseCount": assignment.case_count,
        "warnings": warnings,
    })
    log_schedule_change(
        db,
        event_type="block_or_assignment_updated",
        surgeon_id=surgeon_id,
        admin_user_id=admin_id,
        event_date=block.date,
        title="Block OR assignment updated",
        body=label,
        payload={"blockId": block.id, "assignmentId": assignment.id, "warnings": warnings},
    )
    db.commit()
    db.refresh(block)
    db.expire(block, ["assignments"])
    notify_ids = {previous_surgeon_id, surgeon_id}
    for notify_id in notify_ids:
        if not notify_id:
            continue
        send_native_push_to_surgeon(
            notify_id,
            "Block OR updated",
            label,
            db,
            {"kind": "block_or", "blockId": block.id, "date": block.date.isoformat()},
        )
    return block, warnings


def _sync_legacy_assignment_fields(db: Session, block: ORBlockInstance) -> None:
    """Keep legacy single-assignment columns aligned with remaining ORBlockAssignment rows."""
    db.flush()
    assignments = (
        db.query(ORBlockAssignment)
        .filter(ORBlockAssignment.block_instance_id == block.id)
        .order_by(ORBlockAssignment.start_time, ORBlockAssignment.id)
        .all()
    )
    if not assignments:
        block.assigned_surgeon_id = None
        block.assigned_by_admin_id = None
        block.assigned_at = None
        block.assigned_start_time = None
        block.assigned_case_count = None
        block.assignment_note = None
        block.status = "open"
        return
    first = assignments[0]
    block.assigned_surgeon_id = first.surgeon_id
    block.assigned_by_admin_id = first.assigned_by_admin_id
    block.assigned_at = first.created_at or datetime.now(timezone.utc)
    block.assigned_start_time = first.start_time
    block.assigned_case_count = first.case_count
    block.assignment_note = first.note
    block.status = "assigned"


def remove_block_assignment(
    db: Session,
    block_id: int,
    assignment_id: int,
    admin_id: int | None = None,
) -> ORBlockInstance:
    block = (
        db.query(ORBlockInstance)
        .options(joinedload(ORBlockInstance.assignments).joinedload(ORBlockAssignment.surgeon))
        .filter(ORBlockInstance.id == block_id)
        .first()
    )
    if not block:
        raise ValueError("Block not found")
    assignment = next((row for row in (block.assignments or []) if row.id == assignment_id), None)
    if not assignment:
        raise ValueError("Assignment not found")

    previous_surgeon_id = assignment.surgeon_id
    previous_label = _assignment_payload(block, assignment)["label"]
    db.delete(assignment)
    _sync_legacy_assignment_fields(db, block)

    audit_block(db, block.id, admin_id, "assignment_removed", {
        "assignmentId": assignment_id,
        "previousSurgeonId": previous_surgeon_id,
    })
    log_schedule_change(
        db,
        event_type="block_or_assignment_removed",
        surgeon_id=previous_surgeon_id,
        admin_user_id=admin_id,
        event_date=block.date,
        title="Block OR surgeon removed",
        body=previous_label,
        payload={"blockId": block.id, "assignmentId": assignment_id},
    )
    db.commit()
    db.refresh(block)
    db.expire(block, ["assignments"])
    if previous_surgeon_id:
        send_native_push_to_surgeon(
            previous_surgeon_id,
            "Block OR removed",
            previous_label,
            db,
            {"kind": "block_or", "blockId": block.id, "date": block.date.isoformat()},
        )
    return block


def clear_block_assignment(db: Session, block_id: int, admin_id: int | None = None) -> ORBlockInstance:
    block = db.get(ORBlockInstance, block_id)
    if not block:
        raise ValueError("Block not found")
    previous_surgeon_id = block.assigned_surgeon_id
    previous_label = serialize_block_instance(block)["assignmentLabel"]
    for assignment in list(block.assignments or []):
        db.delete(assignment)
    _sync_legacy_assignment_fields(db, block)
    audit_block(db, block.id, admin_id, "assignment_cleared", {"previousSurgeonId": previous_surgeon_id})
    log_schedule_change(
        db,
        event_type="block_or_assignment_cleared",
        surgeon_id=previous_surgeon_id,
        admin_user_id=admin_id,
        event_date=block.date,
        title="Block OR assignment removed",
        body=previous_label or "Block OR assignment removed",
        payload={"blockId": block.id},
    )
    db.commit()
    db.refresh(block)
    db.expire(block, ["assignments"])
    if previous_surgeon_id:
        send_native_push_to_surgeon(
            previous_surgeon_id,
            "Block OR removed",
            previous_label or "Block OR assignment removed",
            db,
            {"kind": "block_or", "blockId": block.id, "date": block.date.isoformat()},
        )
    return block


def candidate_surgeon_rows(db: Session, block: ORBlockInstance) -> list[dict]:
    surgeons = (
        db.query(Surgeon)
        .filter(Surgeon.is_active == True, Surgeon.staff_type == "physician")  # noqa: E712
        .order_by(Surgeon.sort_order, Surgeon.last_name, Surgeon.first_name)
        .all()
    )
    rows = []
    for surgeon in surgeons:
        if not surgeon_is_visible(surgeon):
            continue
        warnings = block_assignment_warnings(db, block, surgeon.id)
        rows.append({
            "surgeon": surgeon,
            "warnings": warnings,
            "availability": _availability_summary(block, warnings),
            "status": "clear" if not warnings else "warning",
        })
    rows.sort(key=lambda row: (0 if row["status"] == "clear" else 1, row["surgeon"].sort_order or 999, row["surgeon"].last_name))
    return rows


def scheduler_native_home(db: Session, start_date: date, end_date: date) -> dict:
    blocks = [serialize_block_instance(row) for row in block_instances_for_range(db, start_date, end_date)]
    changes = recent_schedule_changes(db)
    return {
        "range": {"start": start_date.isoformat(), "end": end_date.isoformat()},
        "blocks": blocks,
        "changes": changes,
    }


def recent_schedule_changes(db: Session, hours: int = 24) -> list[dict]:
    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    rows = (
        db.query(ScheduleChangeEvent)
        .options(joinedload(ScheduleChangeEvent.surgeon))
        .filter(ScheduleChangeEvent.created_at >= since)
        .order_by(ScheduleChangeEvent.created_at.desc(), ScheduleChangeEvent.id.desc())
        .limit(100)
        .all()
    )
    return [
        {
            "id": row.id,
            "type": row.event_type,
            "date": row.date.isoformat() if row.date else None,
            "title": row.title,
            "body": row.body or "",
            "surgeon": row.surgeon.full_name if row.surgeon else "",
            "surgeonInitials": row.surgeon.initials if row.surgeon else "",
            "createdAt": row.created_at.isoformat() if row.created_at else "",
        }
        for row in rows
    ]


def scheduler_digest_recipients(db: Session) -> list[AdminUser]:
    return (
        db.query(AdminUser)
        .filter(
            AdminUser.is_active == True,  # noqa: E712
            AdminUser.role.in_(["scheduler", "admin", "superadmin"]),
            AdminUser.notify_schedule_changes == True,  # noqa: E712
            AdminUser.email.isnot(None),
            AdminUser.email != "",
        )
        .order_by(AdminUser.role.desc(), AdminUser.last_name, AdminUser.first_name, AdminUser.username)
        .all()
    )


def scheduler_digest_payload(db: Session, today: date | None = None) -> dict:
    current = today or datetime.now(timezone.utc).date()
    end_date = current + timedelta(days=14)
    open_blocks = [
        serialize_block_instance(block)
        for block in block_instances_for_range(db, current, end_date)
        if block.status == "open"
    ]
    return {
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "changes": recent_schedule_changes(db),
        "openBlocks": open_blocks,
    }


def scheduler_digest_html(payload: dict) -> str:
    changes = payload.get("changes", [])
    open_blocks = payload.get("openBlocks", [])
    change_rows = "".join(
        f"""
        <tr>
          <td style="padding:8px;border-bottom:1px solid #e5e7eb">{row.get('date') or ''}</td>
          <td style="padding:8px;border-bottom:1px solid #e5e7eb">{row.get('surgeonInitials') or ''}</td>
          <td style="padding:8px;border-bottom:1px solid #e5e7eb"><strong>{row.get('title') or ''}</strong><br><span style="color:#64748b">{row.get('body') or ''}</span></td>
        </tr>
        """
        for row in changes
    ) or '<tr><td colspan="3" style="padding:8px;color:#64748b">No CAL availability-impacting changes in the last 24 hours.</td></tr>'
    block_rows = "".join(
        f"""
        <tr>
          <td style="padding:8px;border-bottom:1px solid #e5e7eb">{row.get('date') or ''}</td>
          <td style="padding:8px;border-bottom:1px solid #e5e7eb">{row.get('locationAbbreviation') or row.get('location') or ''}</td>
          <td style="padding:8px;border-bottom:1px solid #e5e7eb">{row.get('start') or ''}-{row.get('end') or ''}</td>
        </tr>
        """
        for row in open_blocks
    ) or '<tr><td colspan="3" style="padding:8px;color:#64748b">No open Block OR rows in the next 14 days.</td></tr>'
    return f"""
    <div style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;max-width:760px;margin:0 auto;color:#0f172a">
      <h2 style="margin:0 0 4px">CAL Scheduler Daily Digest</h2>
      <p style="margin:0 0 20px;color:#64748b">Non-PHI schedule changes and open Block OR capacity.</p>
      <h3 style="margin:22px 0 8px">Last 24 hours</h3>
      <table style="border-collapse:collapse;width:100%;font-size:14px">
        <thead><tr style="text-align:left;background:#f8fafc"><th style="padding:8px">Date</th><th style="padding:8px">Doc</th><th style="padding:8px">Change</th></tr></thead>
        <tbody>{change_rows}</tbody>
      </table>
      <h3 style="margin:22px 0 8px">Open blocks needing surgeon</h3>
      <table style="border-collapse:collapse;width:100%;font-size:14px">
        <thead><tr style="text-align:left;background:#f8fafc"><th style="padding:8px">Date</th><th style="padding:8px">Location</th><th style="padding:8px">Time</th></tr></thead>
        <tbody>{block_rows}</tbody>
      </table>
    </div>
    """


def send_scheduler_daily_digest(db: Session) -> dict:
    recipients = scheduler_digest_recipients(db)
    payload = scheduler_digest_payload(db)
    html = scheduler_digest_html(payload)
    sent = 0
    for recipient in recipients:
        if send_email(
            to_email=recipient.email,
            subject="CAL scheduler daily digest",
            html_body=html,
        ):
            sent += 1
    return {"recipients": len(recipients), "sent": sent, "changes": len(payload["changes"]), "openBlocks": len(payload["openBlocks"])}
