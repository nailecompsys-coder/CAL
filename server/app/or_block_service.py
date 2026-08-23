"""Block OR scheduling services.

Block OR is practice capacity inventory. It is separate from ClinicSchedule rows
because open block time may exist before any surgeon is assigned.
"""

from __future__ import annotations

import json
import re
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
from .push import send_push_to_surgeon
from .email_service import send_email
from .scheduling_guardrails_service import scheduler_safe_warning
from .surgeon_visibility import surgeon_is_visible


# Desk fax / Kno2 provenance — keep out of scheduler-facing notes.
_INGEST_NOTE_NOISE_RE = re.compile(
    r"(Desk fax\s*#\d+|Kno2\s+\S+|source=\S+|fax schedule|flags:\s*[^·]*)",
    re.IGNORECASE,
)


def sanitize_schedule_note_for_humans(notes: str | None) -> str:
    """Drop ingest provenance tokens; leave only human-written content."""
    text = (notes or "").strip()
    if not text:
        return ""
    text = _INGEST_NOTE_NOISE_RE.sub("", text)
    text = re.sub(r"\s*·\s*", " · ", text)
    text = re.sub(r"^[\s·]+|[\s·]+$", "", text)
    return text.strip()


SESSION_DEFAULTS = {
    "am": (time(7, 0), time(12, 0)),
    "pm": (time(12, 0), time(17, 0)),
    "both": (time(7, 0), time(17, 0)),
    "custom": (time(7, 0), time(12, 0)),
}
SESSION_SPLIT_NOON = time(12, 0)

ACTIVE_BLOCK_STATUSES = {"open", "assigned"}
OPEN_BLOCK_STATUSES = {"open"}
NON_DUPLICATE_BLOCKING_STATUSES = {"open", "assigned"}


def spans_am_and_pm(start_time: time, end_time: time) -> bool:
    """True when a single window crosses noon (should be two cards: AM + PM)."""
    return start_time < SESSION_SPLIT_NOON < end_time


def infer_session_label(start_time: time, end_time: time, stored: str | None = None) -> str:
    if spans_am_and_pm(start_time, end_time):
        return "both"
    if end_time <= SESSION_SPLIT_NOON:
        return "am"
    if start_time >= SESSION_SPLIT_NOON:
        return "pm"
    return normalize_session(stored or "custom")


def am_pm_windows(start_time: time, end_time: time) -> list[tuple[str, time, time]]:
    """Expand a day-spanning window into AM then PM hospital cards."""
    if not spans_am_and_pm(start_time, end_time):
        return [(infer_session_label(start_time, end_time), start_time, end_time)]
    return [
        ("am", start_time, SESSION_SPLIT_NOON),
        ("pm", SESSION_SPLIT_NOON, end_time),
    ]


def _case_room_labels(block: ORBlockInstance) -> list[str]:
    rooms: list[str] = []
    seen: set[str] = set()
    for case in _active_block_cases(block):
        room = (case.room_text or "").strip()
        key = room.upper()
        if room and key not in seen:
            seen.add(key)
            rooms.append(room)
    return rooms


def _display_room_label(block: ORBlockInstance) -> str:
    primary = (block.room_text or "").strip()
    if primary:
        return primary
    return ", ".join(_case_room_labels(block))


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
    room_text: str | None = None


def normalize_room_text(value: str | None) -> str | None:
    """Canonical room key for dual-capacity matching (S03 vs s03). Blank → None."""
    text = " ".join((value or "").strip().split())
    return text.upper() if text else None


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


def rooms_collide(room_a: str | None, room_b: str | None) -> bool:
    """True when both blank or both the same room — dual rooms do not collide."""
    return normalize_room_text(room_a) == normalize_room_text(room_b)


def overlapping_or_blocks(
    db: Session,
    *,
    block_date: date,
    location_id: int,
    start_time: time,
    end_time: time,
    room_text: str | None = None,
    exclude_block_id: int | None = None,
) -> list[ORBlockInstance]:
    """Overlaps at same hospital/day/time that share the same room key (incl. both blank)."""
    q = db.query(ORBlockInstance).filter(
        ORBlockInstance.date == block_date,
        ORBlockInstance.location_id == location_id,
        ORBlockInstance.status.in_(NON_DUPLICATE_BLOCKING_STATUSES),
        ORBlockInstance.start_time < end_time,
        ORBlockInstance.end_time > start_time,
    )
    if exclude_block_id is not None:
        q = q.filter(ORBlockInstance.id != exclude_block_id)
    rows = q.order_by(ORBlockInstance.start_time, ORBlockInstance.id).all()
    return [row for row in rows if rooms_collide(row.room_text, room_text)]


def duplicate_block_messages(db: Session, payload: BlockORCreateInput) -> list[str]:
    weekdays = set(payload.weekdays or [payload.start_date.weekday()])
    location_ids = list(dict.fromkeys(payload.location_ids))
    room = normalize_room_text(payload.room_text)
    windows = am_pm_windows(payload.start_time, payload.end_time)
    messages = []
    seen = set()
    for block_date in daterange(payload.start_date, payload.end_date):
        if payload.recurrence == "once" and block_date != payload.start_date:
            continue
        if payload.recurrence != "once" and block_date.weekday() not in weekdays:
            continue
        for location_id in location_ids:
            for _session, win_start, win_end in windows:
                overlaps = overlapping_or_blocks(
                    db,
                    block_date=block_date,
                    location_id=location_id,
                    start_time=win_start,
                    end_time=win_end,
                    room_text=room,
                )
                for overlap in overlaps:
                    location = overlap.location.name if overlap.location else f"location {location_id}"
                    room_label = normalize_room_text(overlap.room_text) or "shared window"
                    key = (
                        block_date,
                        location_id,
                        win_start,
                        win_end,
                        overlap.start_time,
                        overlap.end_time,
                        normalize_room_text(overlap.room_text),
                        overlap.status,
                    )
                    if key in seen:
                        continue
                    seen.add(key)
                    messages.append(
                        f"{location} {room_label} already has {overlap.status.replace('_', ' ')} block time "
                        f"{block_date.strftime('%a %-m/%-d')} {overlap.start_time.strftime('%H:%M')}-{overlap.end_time.strftime('%H:%M')}."
                    )
    return messages


def flag_block_missing_room(db: Session, block: ORBlockInstance, *, admin_id: int | None = None) -> None:
    """No-op UI flag. Rooms often live on cases; never surface 'No room' on Block OR cards."""
    clear_block_missing_room_flag(db, block.id)
    return


def clear_block_missing_room_flag(db: Session, block_id: int) -> None:
    from .models import AdminNotification

    def _payload_matches_block(payload_text: str) -> bool:
        return (
            f'"blockId": {block_id}' in payload_text
            or f'"blockId":{block_id}' in payload_text
        )

    events = (
        db.query(ScheduleChangeEvent)
        .filter(ScheduleChangeEvent.event_type == "block_missing_room")
        .all()
    )
    for row in events:
        if _payload_matches_block(row.payload or ""):
            db.delete(row)
    for row in db.query(AdminNotification).filter(AdminNotification.kind == "schedule_flag").all():
        payload_text = row.payload or ""
        if "missing_room" not in payload_text:
            continue
        if _payload_matches_block(payload_text):
            db.delete(row)


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


def _overlapping_upsert_target(
    db: Session,
    *,
    block_date: date,
    location_id: int,
    start_time: time,
    end_time: time,
    room_text: str | None,
) -> ORBlockInstance | None:
    """One existing same-room window can take the new times. Two+ is a real collision."""
    overlaps = overlapping_or_blocks(
        db,
        block_date=block_date,
        location_id=location_id,
        start_time=start_time,
        end_time=end_time,
        room_text=room_text,
    )
    if not overlaps:
        return None
    if len(overlaps) == 1:
        return overlaps[0]
    raise ValueError(
        "Duplicate Block OR time: " + " ".join(
            f"{(row.location.name if row.location else 'OR')} "
            f"{normalize_room_text(row.room_text) or 'shared window'} already has "
            f"{row.status.replace('_', ' ')} block time "
            f"{block_date.strftime('%a %-m/%-d')} "
            f"{row.start_time.strftime('%H:%M')}-{row.end_time.strftime('%H:%M')}."
            for row in overlaps[:3]
        )
    )


def create_or_blocks(db: Session, payload: BlockORCreateInput, admin_id: int | None = None) -> dict:
    if payload.start_date > payload.end_date:
        raise ValueError("Start date must be before end date")
    if payload.start_time >= payload.end_time:
        raise ValueError("Start time must be before end time")
    weekdays = set(payload.weekdays or [payload.start_date.weekday()])
    location_ids = list(dict.fromkeys(payload.location_ids))
    if not location_ids:
        raise ValueError("At least one OR location is required")

    room = normalize_room_text(payload.room_text)
    windows = am_pm_windows(payload.start_time, payload.end_time)
    notes = (payload.notes or "").strip() or None
    series: ORBlockSeries | None = None
    created: list[ORBlockInstance] = []
    updated: list[ORBlockInstance] = []

    def ensure_series() -> ORBlockSeries:
        nonlocal series
        if series is not None:
            return series
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
            notes=notes,
            created_by_admin_id=admin_id,
        )
        db.add(series)
        db.flush()
        return series

    for block_date in daterange(payload.start_date, payload.end_date):
        if payload.recurrence == "once" and block_date != payload.start_date:
            continue
        if payload.recurrence != "once" and block_date.weekday() not in weekdays:
            continue
        for location_id in location_ids:
            for session_label, win_start, win_end in windows:
                existing = _overlapping_upsert_target(
                    db,
                    block_date=block_date,
                    location_id=location_id,
                    start_time=win_start,
                    end_time=win_end,
                    room_text=room,
                )
                if existing is not None:
                    updated.append(
                        update_or_block_instance(
                            db,
                            existing.id,
                            session=session_label,
                            start_time=win_start,
                            end_time=win_end,
                            notes=notes,
                            room_text=payload.room_text if room else None,
                            admin_id=admin_id,
                        )
                    )
                    continue
                series_row = ensure_series()
                instance = ORBlockInstance(
                    series_id=series_row.id,
                    location_id=location_id,
                    date=block_date,
                    session=session_label,
                    start_time=win_start,
                    end_time=win_end,
                    room_text=room,
                    status="open",
                    release_deadline=_block_release_deadline(block_date, payload.release_policy_days),
                    notes=notes,
                )
                db.add(instance)
                db.flush()
                audit_block(db, instance.id, admin_id, "created", {
                    "seriesId": series_row.id,
                    "locationId": location_id,
                    "date": block_date.isoformat(),
                    "session": session_label,
                    "room": room,
                })
                if not room:
                    flag_block_missing_room(db, instance, admin_id=admin_id)
                created.append(instance)
    if created:
        db.commit()
    saved = created + updated
    return {
        "series_id": series.id if series else (saved[0].series_id if saved else None),
        "created": len(created),
        "updated": len(updated),
        "instance_ids": [row.id for row in saved],
    }


def update_or_block_instance(
    db: Session,
    block_id: int,
    *,
    location_id: int | None = None,
    session: str | None = None,
    start_time: time | None = None,
    end_time: time | None = None,
    notes: str | None = None,
    room_text: str | None = None,
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
    new_room = normalize_room_text(room_text) if room_text is not None else normalize_room_text(block.room_text)
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
        room_text=new_room,
        exclude_block_id=block.id,
    )
    if overlaps:
        other = overlaps[0]
        loc_label = other.location.name if other.location else "location"
        room_label = normalize_room_text(other.room_text) or "shared window"
        raise ValueError(
            f"Duplicate Block OR time: {loc_label} {room_label} already has "
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
        "room": block.room_text or "",
        "notes": block.notes or "",
    }
    block.location_id = new_location_id
    block.session = new_session
    block.start_time = new_start
    block.end_time = new_end
    if room_text is not None:
        block.room_text = new_room
        if new_room:
            clear_block_missing_room_flag(db, block.id)
        else:
            flag_block_missing_room(db, block, admin_id=admin_id)
    if notes is not None:
        block.notes = notes.strip() or None
    audit_block(db, block.id, admin_id, "updated", {
        "before": before,
        "after": {
            "locationId": block.location_id,
            "session": block.session,
            "start": block.start_time.strftime("%H:%M"),
            "end": block.end_time.strftime("%H:%M"),
            "room": block.room_text or "",
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
            + (f" · {block.room_text}" if block.room_text else "")
        ),
        admin_user_id=admin_id,
        event_date=block.date,
        payload={"blockId": block.id, "locationId": block.location_id, "room": block.room_text},
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
        raise ValueError("This block still has linked surgical cases. Reschedule those cases before deleting the block.")

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


def split_day_spanning_block(
    db: Session,
    block: ORBlockInstance,
    *,
    admin_id: int | None = None,
) -> ORBlockInstance | None:
    """Split one all-day capacity into AM + PM cards; move noon+ surgeons/cases to PM."""
    if not spans_am_and_pm(block.start_time, block.end_time):
        return None

    pm_end = block.end_time
    am_start = block.start_time
    overlaps = overlapping_or_blocks(
        db,
        block_date=block.date,
        location_id=block.location_id,
        start_time=SESSION_SPLIT_NOON,
        end_time=pm_end,
        room_text=block.room_text,
        exclude_block_id=block.id,
    )
    if overlaps:
        # Already has a PM sibling — just truncate this row to AM.
        block.session = "am"
        block.end_time = SESSION_SPLIT_NOON
        audit_block(
            db,
            block.id,
            admin_id,
            "split_to_am",
            {"reason": "day_spanning_truncated", "keptSiblingId": overlaps[0].id},
        )
        db.flush()
        return None

    pm = ORBlockInstance(
        series_id=block.series_id,
        location_id=block.location_id,
        date=block.date,
        session="pm",
        start_time=SESSION_SPLIT_NOON,
        end_time=pm_end,
        room_text=block.room_text,
        status=block.status or "open",
        release_deadline=block.release_deadline,
        notes=block.notes,
    )
    db.add(pm)
    db.flush()

    for assignment in list(block.assignments or []):
        if assignment.start_time >= SESSION_SPLIT_NOON:
            assignment.block_instance_id = pm.id

    for case in list(_active_block_cases(block)):
        if case.start_time and case.start_time >= SESSION_SPLIT_NOON:
            case.or_block_instance_id = pm.id

    block.session = "am"
    block.start_time = am_start
    block.end_time = SESSION_SPLIT_NOON
    db.flush()
    db.expire(block, ["assignments", "cases"])
    db.expire(pm, ["assignments", "cases"])
    block = _block_with_case_relations(db, block.id) or block
    pm = _block_with_case_relations(db, pm.id) or pm

    # Ensure each PM case has its surgeon on the PM card.
    pm_assigned = {row.surgeon_id for row in (pm.assignments or []) if row.surgeon_id}
    for case in _active_block_cases(pm):
        if not case.surgeon_id or case.surgeon_id in pm_assigned:
            continue
        db.add(
            ORBlockAssignment(
                block_instance_id=pm.id,
                surgeon_id=case.surgeon_id,
                assigned_by_admin_id=admin_id,
                start_time=case.start_time or SESSION_SPLIT_NOON,
                case_count=1,
                note="Moved with case when all-day block was split into AM/PM",
            )
        )
        pm_assigned.add(case.surgeon_id)
    db.flush()
    db.expire(pm, ["assignments", "cases"])
    pm = _block_with_case_relations(db, pm.id) or pm

    _sync_assignment_case_counts_from_cases(db, block)
    _sync_assignment_case_counts_from_cases(db, pm)
    if (pm.assignments or []) or _active_block_cases(pm):
        pm.status = "assigned"
    elif pm.status == "assigned":
        pm.status = "open"
    if (block.assignments or []) or _active_block_cases(block):
        block.status = "assigned"
    elif block.status == "assigned":
        block.status = "open"

    audit_block(
        db,
        block.id,
        admin_id,
        "split_am_pm",
        {
            "amId": block.id,
            "pmId": pm.id,
            "am": f"{block.start_time.strftime('%H:%M')}-{block.end_time.strftime('%H:%M')}",
            "pm": f"{pm.start_time.strftime('%H:%M')}-{pm.end_time.strftime('%H:%M')}",
        },
    )
    audit_block(db, pm.id, admin_id, "created_from_split", {"sourceBlockId": block.id})
    return pm


def ensure_am_pm_split_for_range(db: Session, start_date: date, end_date: date) -> int:
    """Repair day-spanning Block OR rows into AM + PM cards for the visible range."""
    candidates = (
        db.query(ORBlockInstance)
        .options(
            joinedload(ORBlockInstance.assignments),
            joinedload(ORBlockInstance.cases),
        )
        .filter(ORBlockInstance.date >= start_date, ORBlockInstance.date <= end_date)
        .order_by(ORBlockInstance.date, ORBlockInstance.id)
        .all()
    )
    split_count = 0
    for block in candidates:
        if not spans_am_and_pm(block.start_time, block.end_time):
            continue
        if split_day_spanning_block(db, block) is not None or block.session == "am":
            split_count += 1
    if split_count:
        db.commit()
    return split_count


def block_instances_for_range(db: Session, start_date: date, end_date: date) -> list[ORBlockInstance]:
    ensure_am_pm_split_for_range(db, start_date, end_date)
    return (
        db.query(ORBlockInstance)
        .filter(ORBlockInstance.date >= start_date, ORBlockInstance.date <= end_date)
        .options(
            joinedload(ORBlockInstance.location),
            joinedload(ORBlockInstance.assigned_surgeon),
            joinedload(ORBlockInstance.assignments).joinedload(ORBlockAssignment.surgeon),
            joinedload(ORBlockInstance.cases),
        )
        .order_by(
            ORBlockInstance.date,
            ORBlockInstance.start_time,
            ORBlockInstance.location_id,
            ORBlockInstance.id,
        )
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
    room = _display_room_label(block)
    cases = assignment.case_count or 0
    case_word = "Case" if cases == 1 else "Cases"
    initials = assignment.surgeon.initials if assignment.surgeon else ""
    parts = []
    if room and "," not in room:
        parts.append(f"Rm {room}")
    parts.append(assignment.start_time.strftime("%H:%M"))
    parts.append(f"{cases} {case_word}")
    if initials:
        parts.append(initials)
    return {
        "id": assignment.id,
        "surgeonId": assignment.surgeon_id,
        "surgeon": assignment.surgeon.full_name if assignment.surgeon else "",
        "surgeonInitials": initials,
        "start": assignment.start_time.strftime("%H:%M"),
        "caseCount": cases,
        "note": sanitize_schedule_note_for_humans(assignment.note),
        "room": room,
        "label": " · ".join(parts),
    }


def _surgical_case_payload(case: SurgicalCase, *, include_details: bool = True) -> dict:
    payload = {
        "id": case.id,
        "surgeonId": case.surgeon_id,
        "start": case.start_time.strftime("%H:%M") if case.start_time else "",
        "end": case.end_time.strftime("%H:%M") if case.end_time else "",
        "procedure": "",
        "patientName": "",
        "room": (case.room_text or "").strip(),
    }
    if include_details:
        payload["procedure"] = (case.procedure or "").strip()
        payload["patientName"] = (case.patient_name or "").strip()
    return payload


def block_case_payloads(block: ORBlockInstance, *, include_details: bool = True) -> list[dict]:
    rows = [
        case
        for case in list(block.cases or [])
        if (case.status or "").lower() != "cancelled"
    ]
    rows.sort(key=lambda row: (row.start_time or time(0, 0), row.id or 0))
    return [_surgical_case_payload(case, include_details=include_details) for case in rows]


def _active_block_cases(block: ORBlockInstance) -> list[SurgicalCase]:
    return [
        case
        for case in list(block.cases or [])
        if (case.status or "").lower() != "cancelled"
    ]


def _block_with_case_relations(db: Session, block_id: int) -> ORBlockInstance | None:
    return (
        db.query(ORBlockInstance)
        .options(
            joinedload(ORBlockInstance.location),
            joinedload(ORBlockInstance.assignments).joinedload(ORBlockAssignment.surgeon),
            joinedload(ORBlockInstance.assigned_surgeon),
            joinedload(ORBlockInstance.cases),
        )
        .filter(ORBlockInstance.id == block_id)
        .first()
    )


def _sync_assignment_case_counts_from_cases(db: Session, block: ORBlockInstance) -> None:
    """When real cases exist for a surgeon, keep assignment.case_count aligned."""
    active = _active_block_cases(block)
    by_surgeon: dict[int, int] = defaultdict(int)
    for case in active:
        if case.surgeon_id:
            by_surgeon[case.surgeon_id] += 1
    for assignment in list(block.assignments or []):
        counted = by_surgeon.get(assignment.surgeon_id or 0, 0)
        if counted > 0:
            assignment.case_count = counted
    _sync_legacy_assignment_fields(db, block)


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


def serialize_block_instance(block: ORBlockInstance, *, include_case_details: bool = True) -> dict:
    assignments = block_assignment_payloads(block)
    cases = block_case_payloads(block, include_details=include_case_details)
    first_assignment = assignments[0] if assignments else None
    assigned_start = parse_hhmm(first_assignment["start"], block.start_time) if first_assignment else (block.assigned_start_time or block.start_time)
    total_cases = len(cases) if cases else (
        sum(row["caseCount"] for row in assignments) if assignments else (block.assigned_case_count or 0)
    )
    assignment_label = first_assignment["label"] if first_assignment else ""
    status = "assigned" if assignments else (block.status or "open")
    room = _display_room_label(block)
    session = infer_session_label(block.start_time, block.end_time, block.session)
    return {
        "id": block.id,
        "date": block.date.isoformat(),
        "session": session,
        "start": block.start_time.strftime("%H:%M"),
        "end": block.end_time.strftime("%H:%M"),
        "status": status,
        "locationId": block.location_id,
        "location": block.location.name if block.location else "",
        "locationAbbreviation": block.location.abbreviation if block.location else "",
        "room": room,
        "surgeonId": first_assignment["surgeonId"] if first_assignment else block.assigned_surgeon_id,
        "surgeon": first_assignment["surgeon"] if first_assignment else (block.assigned_surgeon.full_name if block.assigned_surgeon else None),
        "surgeonInitials": first_assignment["surgeonInitials"] if first_assignment else _safe_surgeon_label(block.assigned_surgeon),
        "assignedStart": assigned_start.strftime("%H:%M") if assigned_start else None,
        "caseCount": total_cases,
        "assignmentNote": sanitize_schedule_note_for_humans(block.assignment_note),
        "assignmentLabel": assignment_label,
        "assignments": assignments,
        "cases": cases,
        "notes": sanitize_schedule_note_for_humans(block.notes),
    }


def add_case_to_block(
    db: Session,
    block_id: int,
    surgeon_id: int,
    start_time: time,
    *,
    end_time: time | None = None,
    procedure: str = "",
    patient_name: str = "",
    admin_id: int | None = None,
) -> tuple[ORBlockInstance, list[str]]:
    block = _block_with_case_relations(db, block_id)
    if not block:
        raise ValueError("Block not found")
    assigned_ids = {row.surgeon_id for row in (block.assignments or []) if row.surgeon_id}
    if block.assigned_surgeon_id:
        assigned_ids.add(block.assigned_surgeon_id)
    if surgeon_id not in assigned_ids:
        # Adding a case places the surgeon on the block (same idea as reschedule).
        db.add(
            ORBlockAssignment(
                block_instance_id=block.id,
                surgeon_id=surgeon_id,
                assigned_by_admin_id=admin_id,
                start_time=start_time,
                case_count=1,
                note=None,
            )
        )
        db.flush()
        _sync_legacy_assignment_fields(db, block)
        db.expire(block, ["assignments"])
        block = _block_with_case_relations(db, block_id)
        if not block:
            raise ValueError("Block not found")
    if start_time < block.start_time or start_time >= block.end_time:
        raise ValueError("Case start must fall inside the block window")
    if end_time is not None and end_time <= start_time:
        raise ValueError("Case end must be after start")

    case = SurgicalCase(
        surgeon_id=surgeon_id,
        date=block.date,
        start_time=start_time,
        end_time=end_time,
        patient_name=(patient_name or "").strip() or "TBD",
        procedure=(procedure or "").strip() or "Scheduled case",
        location_id=block.location_id,
        or_block_instance_id=block.id,
        room_text=(block.room_text or "").strip() or None,
        status="scheduled",
    )
    db.add(case)
    db.flush()
    db.expire(block, ["cases", "assignments"])
    block = _block_with_case_relations(db, block_id)
    if not block:
        raise ValueError("Block not found")
    _sync_assignment_case_counts_from_cases(db, block)
    warnings = []
    try:
        from .scheduling_guardrails_service import surgical_case_warning_messages

        warnings = surgical_case_warning_messages(
            db,
            surgeon_id,
            block.date,
            start_time,
            end_time,
            block.location_id,
            exclude_case_id=case.id,
        ) or []
    except Exception:
        warnings = []
    log_schedule_change(
        db,
        event_type="surgical_case_added",
        surgeon_id=surgeon_id,
        admin_user_id=admin_id,
        event_date=block.date,
        title="Case added to Block OR",
        body=f"{start_time.strftime('%H:%M')} · {(procedure or 'Scheduled case').strip() or 'Scheduled case'}",
        payload={"blockId": block.id, "caseId": case.id},
    )
    db.commit()
    block = _block_with_case_relations(db, block_id)
    return block, [scheduler_safe_warning(w) for w in warnings if w]


def update_block_case(
    db: Session,
    block_id: int,
    case_id: int,
    *,
    start_time: time | None = None,
    end_time: time | None = None,
    procedure: str | None = None,
    patient_name: str | None = None,
    surgeon_id: int | None = None,
    target_block_id: int | None = None,
    admin_id: int | None = None,
) -> tuple[ORBlockInstance, list[str]]:
    source = _block_with_case_relations(db, block_id)
    if not source:
        raise ValueError("Block not found")
    case = next((row for row in _active_block_cases(source) if row.id == case_id), None)
    if not case:
        raise ValueError("Case not found on this block")

    dest_id = int(target_block_id) if target_block_id is not None else block_id
    dest = source if dest_id == block_id else _block_with_case_relations(db, dest_id)
    if not dest:
        raise ValueError("Destination block not found")

    next_surgeon = int(surgeon_id) if surgeon_id is not None else case.surgeon_id
    if not next_surgeon:
        raise ValueError("Surgeon is required")
    next_start = start_time if start_time is not None else case.start_time
    next_end = end_time if end_time is not None else case.end_time
    if next_start is None:
        raise ValueError("Case start is required")
    # Cross-day reschedule is allowed (insurance / illness). Snap into dest window if needed.
    if next_start < dest.start_time or next_start >= dest.end_time:
        next_start = dest.start_time
    if next_end is not None and next_end <= next_start:
        next_end = None

    assigned_ids = {row.surgeon_id for row in (dest.assignments or []) if row.surgeon_id}
    if dest.assigned_surgeon_id:
        assigned_ids.add(dest.assigned_surgeon_id)
    if next_surgeon not in assigned_ids:
        # Case placement implies the surgeon belongs on the destination block.
        db.add(
            ORBlockAssignment(
                block_instance_id=dest.id,
                surgeon_id=next_surgeon,
                assigned_by_admin_id=admin_id,
                start_time=next_start,
                case_count=1,
                note="Auto-added when case was rescheduled onto this block",
            )
        )
        db.flush()
        _sync_legacy_assignment_fields(db, dest)
        db.expire(dest, ["assignments"])
        dest = _block_with_case_relations(db, dest.id)
        if not dest:
            raise ValueError("Destination block not found")

    case.surgeon_id = next_surgeon
    case.or_block_instance_id = dest.id
    case.location_id = dest.location_id
    case.date = dest.date
    case.start_time = next_start
    if end_time is not None:
        case.end_time = end_time
    if procedure is not None:
        case.procedure = procedure.strip() or case.procedure or "Scheduled case"
    if patient_name is not None:
        case.patient_name = patient_name.strip() or case.patient_name or "TBD"
    if dest.room_text and not (case.room_text or "").strip():
        case.room_text = dest.room_text
    db.flush()
    db.expire(source, ["cases", "assignments"])
    db.expire(dest, ["cases", "assignments"])
    source = _block_with_case_relations(db, block_id)
    dest = _block_with_case_relations(db, dest.id)
    if source:
        _sync_assignment_case_counts_from_cases(db, source)
    if dest and (not source or dest.id != source.id):
        _sync_assignment_case_counts_from_cases(db, dest)

    warnings = []
    try:
        from .scheduling_guardrails_service import surgical_case_warning_messages

        warnings = surgical_case_warning_messages(
            db,
            next_surgeon,
            dest.date if dest else case.date,
            case.start_time,
            case.end_time,
            dest.location_id if dest else case.location_id,
            exclude_case_id=case.id,
        ) or []
    except Exception:
        warnings = []

    moved = dest is not None and dest.id != block_id
    log_schedule_change(
        db,
        event_type="surgical_case_moved" if moved else "surgical_case_updated",
        surgeon_id=next_surgeon,
        admin_user_id=admin_id,
        event_date=case.date,
        title="Case moved to another Block OR" if moved else "Case updated on Block OR",
        body=f"{case.start_time.strftime('%H:%M')} · {(case.procedure or 'Case').strip()}",
        payload={
            "blockId": block_id,
            "targetBlockId": dest.id if dest else block_id,
            "caseId": case.id,
            "fromDate": source.date.isoformat() if source else None,
            "toDate": dest.date.isoformat() if dest else None,
        },
    )
    db.commit()
    # Always return the source block so the open editor stays on the same sheet.
    source = _block_with_case_relations(db, block_id)
    return source, [scheduler_safe_warning(w) for w in warnings if w]


def copy_or_block_capacity(
    db: Session,
    *,
    source_week_start: date,
    weekdays: list[int],
    end_date: date,
    location_id: int | None = None,
    source_block_id: int | None = None,
    admin_id: int | None = None,
) -> dict:
    """Copy open capacity forward one weekday → same weekday until end_date.

    Capacity only (no surgeon assignments). Skips target days that already have a
    colliding room/time at that hospital and returns skip notes.
    """
    weekdays_set = {int(day) for day in weekdays}
    if not weekdays_set:
        raise ValueError("Select at least one weekday to copy")
    if end_date < source_week_start:
        raise ValueError("Copy end date must be on or after the source week")

    source_week_end = source_week_start + timedelta(days=6)
    q = (
        db.query(ORBlockInstance)
        .options(joinedload(ORBlockInstance.location))
        .filter(
            ORBlockInstance.date >= source_week_start,
            ORBlockInstance.date <= source_week_end,
            ORBlockInstance.status.in_(ACTIVE_BLOCK_STATUSES),
        )
    )
    if location_id is not None:
        q = q.filter(ORBlockInstance.location_id == int(location_id))
    if source_block_id is not None:
        q = q.filter(ORBlockInstance.id == int(source_block_id))
    sources = [
        row for row in q.order_by(ORBlockInstance.date, ORBlockInstance.location_id, ORBlockInstance.id).all()
        if row.date.weekday() in weekdays_set
    ]
    if not sources:
        raise ValueError("No Block OR capacity found for the selected weekdays in this week")

    created = 0
    skipped: list[str] = []
    # Horizon starts the week after the source week (do not recreate source days).
    cursor_week = source_week_start + timedelta(days=7)
    while cursor_week <= end_date:
        for source in sources:
            target_date = cursor_week + timedelta(days=source.date.weekday())
            if target_date > end_date:
                continue
            if target_date.weekday() != source.date.weekday():
                continue
            room = normalize_room_text(source.room_text)
            overlaps = overlapping_or_blocks(
                db,
                block_date=target_date,
                location_id=source.location_id,
                start_time=source.start_time,
                end_time=source.end_time,
                room_text=room,
            )
            loc_label = (
                source.location.abbreviation if source.location and source.location.abbreviation
                else (source.location.name if source.location else f"location {source.location_id}")
            )
            room_label = room or "shared window"
            if overlaps:
                skipped.append(
                    f"Skipped {loc_label} {room_label} {target_date.strftime('%a %-m/%-d')} "
                    f"{source.start_time.strftime('%H:%M')}-{source.end_time.strftime('%H:%M')} "
                    "(already has block time)."
                )
                continue
            try:
                result = create_or_blocks(
                    db,
                    BlockORCreateInput(
                        name=f"Copy · {loc_label}",
                        start_date=target_date,
                        end_date=target_date,
                        weekdays=[target_date.weekday()],
                        location_ids=[source.location_id],
                        session=source.session or "custom",
                        start_time=source.start_time,
                        end_time=source.end_time,
                        recurrence="once",
                        notes=source.notes,
                        room_text=room,
                    ),
                    admin_id=admin_id,
                )
                created += int(result.get("created") or 0)
            except ValueError as exc:
                skipped.append(
                    f"Skipped {loc_label} room {room_label} {target_date.strftime('%a %-m/%-d')}: {exc}"
                )
        cursor_week += timedelta(days=7)

    return {
        "created": created,
        "skipped": skipped,
        "source_count": len(sources),
        "end_date": end_date.isoformat(),
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
            "type": "or_block",
            "date": block.date,
            "start_time": start,
            "end_time": end,
            "location_id": block.location_id,
            "or_block_instance_id": block.id,
            "block_id": block.id,
        },
    )
    for conflict in conflicts:
        # Surgical cases belong inside this Block OR — not a conflict for Shannon.
        if conflict.rule_id == "OVERLAP_SURGERY":
            continue
        # On-call + Block OR is expected at any hospital — not a scheduling flag.
        if conflict.rule_id == "OVERLAP_CALL":
            continue
        # Do not flag this block against itself.
        if conflict.rule_id == "OVERLAP_OR_BLOCK" and conflict.conflicting_entity_id == block.id:
            continue
        label = {
            "OVERLAP_SURGERY": "Overlaps another surgical case",
            "OVERLAP_CLINIC": "Overlaps clinic schedule",
            "OVERLAP_DAY_OFF": "Overlaps day off",
            "OVERLAP_MEETING": "Overlaps assigned meeting",
            "OVERLAP_UNAVAILABLE": "Overlaps unavailable time",
            "OVERLAP_OR_BLOCK": "Overlaps another OR block assignment",
        }.get(conflict.rule_id, "Schedule warning")
        warnings.append(scheduler_safe_warning(f"{label}: {conflict.message}"))

    from .models import SurgeonDayItem
    personal_items = db.query(SurgeonDayItem).filter(
        SurgeonDayItem.surgeon_id == surgeon_id,
        SurgeonDayItem.date == block.date,
    ).all()
    for item in personal_items:
        item_start = item.start_time or time(0, 0)
        item_end = item.end_time or time(23, 59)
        if item_start < end and item_end > start:
            title = (item.title or "Personal time").strip()
            warnings.append(scheduler_safe_warning(f"Overlaps personal item: {title}"))
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


def _notify_block_or_surgeon(
    db: Session,
    surgeon_id: int | None,
    *,
    title: str,
    body: str,
    block: ORBlockInstance,
) -> None:
    """Immediate doctor notify: in-app alert + web push + native push."""
    if not surgeon_id:
        return
    send_push_to_surgeon(
        surgeon_id,
        title,
        body,
        db,
        data={
            "kind": "block_or",
            "type": "block_or",
            "blockId": block.id,
            "date": block.date.isoformat() if block.date else None,
        },
    )


def assign_block(
    db: Session,
    block_id: int,
    surgeon_id: int,
    admin_id: int | None = None,
    assigned_start_time: time | None = None,
    case_count: int | None = None,
    assignment_note: str | None = None,
    *,
    notify: bool = True,
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
    note = (assignment_note or "").strip() or None
    if warnings and not note:
        raise ValueError(
            "Add a note to override schedule warnings: " + "; ".join(warnings[:3])
        )
    assignment = ORBlockAssignment(
        block_instance_id=block.id,
        surgeon_id=surgeon_id,
        assigned_by_admin_id=admin_id,
        start_time=assigned_start,
        case_count=max(1, int(case_count or 1)),
        note=note,
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
    # Fixed placement ⇒ drop prior admin schedule flags for this surgeon/block.
    from .push import clear_block_or_schedule_flag_notifications

    if not warnings:
        clear_block_or_schedule_flag_notifications(db, block.id, surgeon_id)
    if notify:
        _notify_block_or_surgeon(
            db,
            surgeon_id,
            title="Block OR updated",
            body=label,
            block=block,
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
    *,
    notify: bool = True,
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
    note = (assignment_note or "").strip() or None
    if warnings and not note:
        raise ValueError(
            "Add a note to override schedule warnings: " + "; ".join(warnings[:3])
        )
    assignment.surgeon_id = surgeon_id
    assignment.assigned_by_admin_id = admin_id
    assignment.start_time = assigned_start
    assignment.case_count = max(1, int(case_count if case_count is not None else assignment.case_count or 1))
    assignment.note = note
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
    from .push import clear_block_or_schedule_flag_notifications

    if previous_surgeon_id and previous_surgeon_id != surgeon_id:
        clear_block_or_schedule_flag_notifications(db, block.id, previous_surgeon_id)
    if not warnings:
        clear_block_or_schedule_flag_notifications(db, block.id, surgeon_id)
    if notify:
        if previous_surgeon_id and previous_surgeon_id != surgeon_id:
            _notify_block_or_surgeon(
                db,
                previous_surgeon_id,
                title="Block OR removed",
                body=label,
                block=block,
            )
        _notify_block_or_surgeon(
            db,
            surgeon_id,
            title="Block OR updated",
            body=label,
            block=block,
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
        .options(
            joinedload(ORBlockInstance.assignments).joinedload(ORBlockAssignment.surgeon),
            joinedload(ORBlockInstance.cases),
        )
        .filter(ORBlockInstance.id == block_id)
        .first()
    )
    if not block:
        raise ValueError("Block not found")
    assignment = next((row for row in (block.assignments or []) if row.id == assignment_id), None)
    if not assignment:
        raise ValueError("Assignment not found")
    linked = [
        case
        for case in _active_block_cases(block)
        if case.surgeon_id == assignment.surgeon_id
    ]
    if linked:
        raise ValueError(
            "This surgeon still has linked surgical cases on this block. "
            "Reschedule those cases before removing the surgeon."
        )

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
    from .push import clear_block_or_schedule_flag_notifications

    if previous_surgeon_id:
        clear_block_or_schedule_flag_notifications(db, block.id, previous_surgeon_id)
        _notify_block_or_surgeon(
            db,
            previous_surgeon_id,
            title="Block OR removed",
            body=previous_label,
            block=block,
        )
    return block


def clear_block_assignment(db: Session, block_id: int, admin_id: int | None = None) -> ORBlockInstance:
    block = (
        db.query(ORBlockInstance)
        .options(
            joinedload(ORBlockInstance.assignments),
            joinedload(ORBlockInstance.cases),
        )
        .filter(ORBlockInstance.id == block_id)
        .first()
    )
    if not block:
        raise ValueError("Block not found")
    active_cases = [
        case
        for case in list(block.cases or [])
        if (case.status or "").lower() != "cancelled"
    ]
    if active_cases:
        raise ValueError(
            "This block still has linked surgical cases. Reschedule those cases before clearing surgeons."
        )
    # Capture every assigned surgeon before rows are deleted.
    notify_targets: list[tuple[int, str]] = []
    for assignment in list(block.assignments or []):
        if assignment.surgeon_id:
            notify_targets.append(
                (assignment.surgeon_id, _assignment_payload(block, assignment)["label"])
            )
    if not notify_targets and block.assigned_surgeon_id:
        notify_targets.append(
            (
                block.assigned_surgeon_id,
                serialize_block_instance(block)["assignmentLabel"] or "Block OR assignment removed",
            )
        )
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
    from .push import clear_block_or_schedule_flag_notifications

    seen: set[int] = set()
    for surgeon_id, label in notify_targets:
        if surgeon_id in seen:
            continue
        seen.add(surgeon_id)
        clear_block_or_schedule_flag_notifications(db, block.id, surgeon_id)
        _notify_block_or_surgeon(
            db,
            surgeon_id,
            title="Block OR removed",
            body=label or "Block OR assignment removed",
            block=block,
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
    # Week list omits case PHI; block detail returns full case rows for schedulers.
    blocks = [
        serialize_block_instance(row, include_case_details=False)
        for row in block_instances_for_range(db, start_date, end_date)
    ]
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
    out = []
    for row in rows:
        payload = {}
        if row.payload:
            try:
                payload = json.loads(row.payload)
            except (TypeError, ValueError):
                payload = {}
        out.append({
            "id": row.id,
            "type": row.event_type,
            "date": row.date.isoformat() if row.date else None,
            "title": row.title,
            "body": row.body or "",
            "surgeon": row.surgeon.full_name if row.surgeon else "",
            "surgeonInitials": row.surgeon.initials if row.surgeon else "",
            "createdAt": row.created_at.isoformat() if row.created_at else "",
            "href": payload.get("href") or (
                f"/admin/block-or?block_id={payload['blockId']}" if payload.get("blockId") else "/admin/block-or"
            ),
            "blockId": payload.get("blockId"),
        })
    return out


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
