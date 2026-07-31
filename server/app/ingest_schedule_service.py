"""Desk → CAL schedule ingest: Block OR capacity + surgical cases + clinic day lanes.

OR fax times become Block OR windows (practice capacity) with cases under them.
Clinic fax times become ClinicSchedule day/session assignments (notes carry clock times
until ClinicSchedule has real start/end columns).

Re-ingest semantics (daily faxes covering the same window):
- identical case → ignore (no overlay)
- time / room / procedure / facility change → update existing row
- new patient on that day → create
- fax-sourced case missing from the day's fax list → cancel
Identity is surgeon + date + normalized patient name (NOT start time).
"""
from __future__ import annotations

import json
import re
from collections import defaultdict
from datetime import date, datetime, time, timedelta
from typing import Any

from sqlalchemy.orm import Session

from .admin_surgical_schedule_service import add_surgical_case
from .ingest_resolve import resolve_clinic_location, resolve_or_location, resolve_surgeon
from .models import ClinicSchedule, ORBlockAssignment, ORBlockInstance, SurgicalCase
from .or_block_service import (
    ACTIVE_BLOCK_STATUSES,
    BlockORCreateInput,
    assign_block,
    block_assignment_warnings,
    create_or_blocks,
    log_schedule_change,
    parse_hhmm,
    update_block_assignment,
    update_or_block_instance,
)
from .push import clear_block_or_schedule_flag_notifications, notify_admins

_DESK_SOURCE_RE = re.compile(r"(Desk fax\s*#|source=desk)", re.IGNORECASE)
_PATIENT_NOISE_RE = re.compile(
    r"\b(md|do|jr|sr|ii|iii|iv|femoral|incart|of|es|stolar|gensrg|wgdgs|ahmggensrg)\b",
    re.IGNORECASE,
)


def _parse_date(raw: str | None) -> date | None:
    if not raw or not str(raw).strip():
        return None
    try:
        return date.fromisoformat(str(raw).strip()[:10])
    except ValueError:
        return None


def _parse_time(raw: str | None, fallback: time | None = None) -> time | None:
    s = (raw or "").strip()
    if not s:
        return fallback
    try:
        return parse_hhmm(s)
    except ValueError:
        return fallback


def _block_window_for_cases(
    cases: list[dict],
    session: str,
    explicit_start: str | None = None,
    explicit_end: str | None = None,
) -> tuple[time, time]:
    """Fax times are SSOT. Do not invent AM/PM defaults when case clocks exist."""
    start = _parse_time(explicit_start)
    end = _parse_time(explicit_end)
    times = [t for t in (_parse_time(c.get("start_time")) for c in cases) if t is not None]
    if start is None and times:
        start = min(times)
    if end is None and times:
        latest = max(times)
        # Cover last listed case start; Shannon can edit the block end in portal.
        end = (datetime.combine(date.today(), latest) + timedelta(minutes=90)).time()
    if start is None or end is None:
        raise ValueError(
            "Fax OR block missing case/block times — cannot invent a window "
            f"(session={session or 'am'})"
        )
    if start >= end:
        end = (datetime.combine(date.today(), start) + timedelta(hours=4)).time()
    return start, end


def _same_day_facility_block(
    db: Session,
    *,
    block_date: date,
    location_id: int,
    room_text: str | None = None,
) -> ORBlockInstance | None:
    """Prefer existing Block OR on that date/facility/room (dual rooms stay separate)."""
    from .or_block_service import normalize_room_text, rooms_collide

    rows = (
        db.query(ORBlockInstance)
        .filter(
            ORBlockInstance.date == block_date,
            ORBlockInstance.location_id == location_id,
            ORBlockInstance.status.in_(ACTIVE_BLOCK_STATUSES),
        )
        .order_by(ORBlockInstance.start_time, ORBlockInstance.id)
        .all()
    )
    room = normalize_room_text(room_text)
    for row in rows:
        if rooms_collide(row.room_text, room):
            return row
    return None


def _ensure_or_block_for_fax(
    db: Session,
    *,
    block_date: date,
    location_id: int,
    start_time: time,
    end_time: time,
    session: str,
    notes: str,
    room_text: str | None = None,
) -> tuple[ORBlockInstance, str]:
    """Create missing Block OR, or expand an existing one to fit fax SSOT times.

    Room is part of identity: S03 and S08 at the same hospital/day/time are dual
    capacity rows. Same room (or both blank) reuses/expands one row so two docs
    in one room become two assignments on one block.

    Returns (block, action) where action is created | expanded | reused.
    """
    from .or_block_service import normalize_room_text

    room = normalize_room_text(room_text)
    existing = _same_day_facility_block(
        db, block_date=block_date, location_id=location_id, room_text=room
    )
    if existing:
        new_start = min(existing.start_time, start_time)
        new_end = max(existing.end_time, end_time)
        if new_start != existing.start_time or new_end != existing.end_time:
            note = (existing.notes or "").strip()
            merged = notes if not note else (note if notes in note else f"{note} · {notes}")
            block = update_or_block_instance(
                db,
                existing.id,
                start_time=new_start,
                end_time=new_end,
                notes=merged,
                admin_id=None,
            )
            return block, "expanded"
        return existing, "reused"

    created = create_or_blocks(
        db,
        BlockORCreateInput(
            name=f"Desk OR {block_date.isoformat()}",
            start_date=block_date,
            end_date=block_date,
            weekdays=[block_date.weekday()],
            location_ids=[location_id],
            session=session if session in {"am", "pm", "both", "custom"} else "custom",
            start_time=start_time,
            end_time=end_time,
            recurrence="once",
            notes=notes,
            room_text=room,
        ),
        admin_id=None,
    )
    block = db.get(ORBlockInstance, created["instance_ids"][0])
    if not block:
        raise ValueError("Failed to create Block OR instance")
    return block, "created"


def _assign_surgeon_to_block(
    db: Session,
    *,
    block: ORBlockInstance,
    surgeon_id: int,
    assigned_start: time,
    case_count: int,
    base_note: str,
) -> list[str]:
    """Place surgeon on block; fax SSOT overrides schedule warnings with a note.

    Always returns top-down conflict warnings for Shannon flags.
    """
    warnings = block_assignment_warnings(
        db, block, surgeon_id, assigned_start, block.end_time
    )
    note = base_note
    if warnings:
        note = (f"{base_note} · flags: " + "; ".join(warnings[:4])).strip(" ·") if base_note else (
            "flags: " + "; ".join(warnings[:4])
        )
    elif base_note:
        note = base_note
    else:
        note = ""

    existing = (
        db.query(ORBlockAssignment)
        .filter(
            ORBlockAssignment.block_instance_id == block.id,
            ORBlockAssignment.surgeon_id == surgeon_id,
        )
        .order_by(ORBlockAssignment.start_time, ORBlockAssignment.id)
        .first()
    )
    if existing:
        update_block_assignment(
            db,
            block.id,
            existing.id,
            surgeon_id,
            admin_id=None,
            assigned_start_time=assigned_start,
            case_count=case_count,
            assignment_note=note,
            notify=False,
        )
    else:
        assign_block(
            db,
            block.id,
            surgeon_id,
            admin_id=None,
            assigned_start_time=assigned_start,
            case_count=case_count,
            assignment_note=note,
            notify=False,
        )
    return warnings


def _clear_desk_or_schedule_flag_events(
    db: Session,
    *,
    block_id: int,
    surgeon_id: int,
) -> None:
    from .models import ScheduleChangeEvent

    rows = (
        db.query(ScheduleChangeEvent)
        .filter(ScheduleChangeEvent.event_type == "desk_or_schedule_flag")
        .all()
    )
    removed = 0
    for row in rows:
        try:
            payload = json.loads(row.payload or "{}") if row.payload else {}
        except (TypeError, ValueError):
            payload = {}
        if str(payload.get("blockId") or "") != str(block_id):
            continue
        if row.surgeon_id is not None and row.surgeon_id != surgeon_id:
            continue
        db.delete(row)
        removed += 1
    if removed:
        db.commit()


def _flag_admin_schedule_issues(
    db: Session,
    *,
    surgeon_id: int,
    surgeon_name: str,
    day: date,
    block: ORBlockInstance,
    location_label: str,
    warnings: list[str],
    fax_note: str,
) -> None:
    # Always replace prior flags for this placement. Fixed ⇒ gone.
    clear_block_or_schedule_flag_notifications(db, block.id, surgeon_id)
    _clear_desk_or_schedule_flag_events(db, block_id=block.id, surgeon_id=surgeon_id)
    if not warnings:
        return
    body = (
        f"{surgeon_name} · {day.strftime('%m-%d-%y')} · {location_label} "
        f"{block.start_time.strftime('%H:%M')}-{block.end_time.strftime('%H:%M')}: "
        + "; ".join(warnings[:5])
    )
    log_schedule_change(
        db,
        event_type="desk_or_schedule_flag",
        title="Desk OR schedule flag",
        body=body,
        surgeon_id=surgeon_id,
        event_date=day,
        payload={
            "blockId": block.id,
            "location": location_label,
            "warnings": warnings,
            "source": fax_note,
            "href": f"/admin/block-or?block_id={block.id}",
        },
    )
    notify_admins(
        title="Scheduling flag · Block OR",
        body=body,
        db=db,
        kind="schedule_flag",
        payload={
            "blockId": block.id,
            "surgeonId": surgeon_id,
            "date": day.isoformat(),
            "warnings": warnings,
            "href": f"/admin/block-or?block_id={block.id}",
        },
        require_schedule_opt_in=True,
    )


def _normalize_patient_parts(name: str | None) -> tuple[str, str]:
    """Return (last, first) tokens for identity matching."""
    raw = " ".join((name or "").strip().lower().split())
    if not raw:
        return "", ""
    raw = raw.replace(".", " ")
    if "," in raw:
        last, _, first = raw.partition(",")
    else:
        bits = raw.split()
        if len(bits) == 1:
            last, first = bits[0], ""
        else:
            last, first = bits[0], " ".join(bits[1:])
    last = _PATIENT_NOISE_RE.sub(" ", last)
    first = _PATIENT_NOISE_RE.sub(" ", first)
    last = " ".join(last.split())
    first = " ".join(first.split())
    return last, first


def _patient_identity_match(a: str | None, b: str | None) -> bool:
    """True when two OCR/patient strings refer to the same person on a day."""
    la, fa = _normalize_patient_parts(a)
    lb, fb = _normalize_patient_parts(b)
    if not la or not lb or la != lb:
        return False
    if not fa or not fb:
        return True
    return fa == fb or fa.startswith(fb) or fb.startswith(fa)


def _is_desk_sourced_case(case: SurgicalCase) -> bool:
    return bool(_DESK_SOURCE_RE.search(case.notes or ""))


def _norm_proc(value: str | None) -> str:
    return " ".join((value or "").strip().lower().split())


def _norm_room(value: str | None) -> str:
    return " ".join((value or "").strip().upper().split())


def _prefer_patient_name(existing: str | None, incoming: str | None) -> str:
    """Keep the more complete display name when identity matches."""
    a = (existing or "").strip()
    b = (incoming or "").strip()
    if not a:
        return b
    if not b:
        return a
    if len(b) > len(a) and _patient_identity_match(a, b):
        return b
    return a


def _find_matching_case(
    candidates: list[SurgicalCase],
    *,
    patient_name: str,
    start_time: time,
    claimed_ids: set[int],
) -> SurgicalCase | None:
    matches = [
        c
        for c in candidates
        if c.id not in claimed_ids and _patient_identity_match(c.patient_name, patient_name)
    ]
    if not matches:
        return None
    exact_time = [c for c in matches if c.start_time == start_time]
    if exact_time:
        return exact_time[0]
    return sorted(matches, key=lambda c: (c.start_time or time(0, 0), c.id))[0]


def _upsert_surgical_case(
    db: Session,
    *,
    surgeon_id: int,
    case_date: date,
    start_time: time,
    patient_name: str,
    procedure: str,
    location_id: int | None,
    room_text: str,
    notes: str,
    or_block_instance_id: int | None,
    notify: bool,
    day_candidates: list[SurgicalCase],
    claimed_ids: set[int],
) -> dict[str, Any]:
    """Create / update / ignore. Identity = surgeon + date + patient (not time)."""
    incoming_name = patient_name.strip()
    incoming_proc = (procedure or "TBD").strip() or "TBD"
    incoming_room = (room_text or "").strip() or None

    existing = _find_matching_case(
        day_candidates,
        patient_name=incoming_name,
        start_time=start_time,
        claimed_ids=claimed_ids,
    )
    if existing is None:
        # Same fax sometimes lists one patient twice with OCR name variants.
        # Never create a second row once that patient is already claimed today.
        already = _find_matching_case(
            day_candidates,
            patient_name=incoming_name,
            start_time=start_time,
            claimed_ids=set(),
        )
        if already is not None and already.id in claimed_ids:
            return {
                "id": already.id,
                "action": "unchanged",
                "case_date": case_date.isoformat(),
                "patient_name": already.patient_name,
                "start_time": (already.start_time or start_time).strftime("%H:%M"),
            }
    if existing:
        claimed_ids.add(existing.id)
        changed = False
        if existing.start_time != start_time:
            existing.start_time = start_time
            changed = True
        if location_id and existing.location_id != location_id:
            existing.location_id = location_id
            changed = True
        if _norm_room(existing.room_text) != _norm_room(incoming_room):
            existing.room_text = incoming_room
            changed = True
        if _norm_proc(existing.procedure) != _norm_proc(incoming_proc):
            existing.procedure = incoming_proc
            changed = True
        preferred = _prefer_patient_name(existing.patient_name, incoming_name)
        if preferred != (existing.patient_name or "").strip():
            existing.patient_name = preferred
            # Name enrichment alone is not a schedule change — keep quiet unless
            # something clinical also moved.
        if or_block_instance_id and existing.or_block_instance_id != or_block_instance_id:
            existing.or_block_instance_id = or_block_instance_id
            changed = True
        if changed:
            # Only rewrite source notes when the row actually moved.
            if notes and not _is_desk_sourced_case(existing):
                existing.notes = notes
            elif notes and "Desk fax" in notes:
                # Keep provenance, but don't stack fax ids on every resend.
                existing.notes = notes
            db.commit()
            return {
                "id": existing.id,
                "action": "updated",
                "case_date": case_date.isoformat(),
                "patient_name": existing.patient_name,
                "start_time": start_time.strftime("%H:%M"),
            }
        return {
            "id": existing.id,
            "action": "unchanged",
            "case_date": case_date.isoformat(),
            "patient_name": existing.patient_name,
            "start_time": (existing.start_time or start_time).strftime("%H:%M"),
        }

    # Cross-surgeon guard: daily faxes / OCR splits must not create a second
    # active row for the same patient on the same day under another surgeon.
    others = (
        db.query(SurgicalCase)
        .filter(
            SurgicalCase.date == case_date,
            SurgicalCase.surgeon_id != surgeon_id,
            SurgicalCase.status != "cancelled",
        )
        .all()
    )
    other_hit = next(
        (c for c in others if _patient_identity_match(c.patient_name, incoming_name)),
        None,
    )
    if other_hit is not None:
        return {
            "id": other_hit.id,
            "action": "skipped_duplicate",
            "case_date": case_date.isoformat(),
            "patient_name": other_hit.patient_name,
            "start_time": start_time.strftime("%H:%M"),
            "existing_surgeon_id": other_hit.surgeon_id,
        }

    fields = {
        "surgeon_id": surgeon_id,
        "date": case_date,
        "start_time": start_time,
        "end_time": None,
        "patient_name": incoming_name,
        "patient_dob": None,
        "patient_phone": None,
        "procedure": incoming_proc,
        "location_id": location_id,
        "room_text": incoming_room,
        "status": "scheduled",
        "notes": notes.strip() or None,
        "or_block_instance_id": or_block_instance_id,
    }
    surgical_case, _warn = add_surgical_case(db, fields, notify=notify)
    claimed_ids.add(surgical_case.id)
    day_candidates.append(surgical_case)
    return {
        "id": surgical_case.id,
        "action": "created",
        "case_date": case_date.isoformat(),
        "patient_name": surgical_case.patient_name,
        "start_time": start_time.strftime("%H:%M"),
    }


def _cancel_missing_desk_cases(
    db: Session,
    *,
    surgeon_id: int,
    case_date: date,
    claimed_ids: set[int],
) -> list[dict[str, Any]]:
    """Cancel fax-sourced cases for this surgeon/day that are not in the new fax."""
    removed: list[dict[str, Any]] = []
    rows = (
        db.query(SurgicalCase)
        .filter(
            SurgicalCase.surgeon_id == surgeon_id,
            SurgicalCase.date == case_date,
            SurgicalCase.status != "cancelled",
        )
        .all()
    )
    dirty = False
    for row in rows:
        if row.id in claimed_ids:
            continue
        if not _is_desk_sourced_case(row):
            continue
        row.status = "cancelled"
        dirty = True
        removed.append({
            "id": row.id,
            "action": "removed",
            "case_date": case_date.isoformat(),
            "patient_name": row.patient_name,
            "start_time": row.start_time.strftime("%H:%M") if row.start_time else None,
        })
    if dirty:
        db.commit()
    return removed


def _clinic_visit_fingerprint(notes: str | None) -> str:
    """Compare clinic visit payloads without caring which Desk fax id wrote them."""
    text = notes or ""
    text = re.sub(r"Desk fax\s*#\d+", "", text, flags=re.IGNORECASE)
    text = re.sub(r"Kno2\s+\S+", "", text, flags=re.IGNORECASE)
    text = re.sub(r"source=\w+", "", text, flags=re.IGNORECASE)
    return " ".join(text.split())


def _upsert_clinic_day(
    db: Session,
    *,
    surgeon_id: int,
    day: date,
    session: str,
    location_id: int,
    notes: str,
) -> dict[str, Any]:
    """Write clinic lane without staff push spam; ignore identical resends."""
    sess = (session or "pm").lower()
    if sess not in {"am", "pm", "full"}:
        sess = "pm"
    existing = (
        db.query(ClinicSchedule)
        .filter(
            ClinicSchedule.surgeon_id == surgeon_id,
            ClinicSchedule.date == day,
            ClinicSchedule.session.in_([sess, "full"]),
        )
        .order_by(ClinicSchedule.id)
        .first()
    )
    if existing:
        same_loc = existing.location_id == location_id
        same_visits = _clinic_visit_fingerprint(existing.notes) == _clinic_visit_fingerprint(notes)
        if same_loc and same_visits and existing.session == sess:
            return {
                "id": existing.id,
                "action": "unchanged",
                "date": day.isoformat(),
                "session": sess,
                "location_id": location_id,
                "warnings": [],
            }
        existing.location_id = location_id
        existing.session = sess
        existing.assignment_type = "assigned"
        existing.notes = notes
        # Drop duplicate session rows for the same day (legacy full/pm collisions).
        extras = (
            db.query(ClinicSchedule)
            .filter(
                ClinicSchedule.surgeon_id == surgeon_id,
                ClinicSchedule.date == day,
                ClinicSchedule.session.in_([sess, "full"]),
                ClinicSchedule.id != existing.id,
            )
            .all()
        )
        for row in extras:
            db.delete(row)
        db.commit()
        return {
            "id": existing.id,
            "action": "updated",
            "date": day.isoformat(),
            "session": sess,
            "location_id": location_id,
            "warnings": [],
        }

    row = ClinicSchedule(
        surgeon_id=surgeon_id,
        location_id=location_id,
        date=day,
        session=sess,
        assignment_type="assigned",
        notes=notes,
    )
    db.add(row)
    db.commit()
    return {
        "id": row.id,
        "action": "created",
        "date": day.isoformat(),
        "session": sess,
        "location_id": location_id,
        "warnings": [],
    }


def ingest_surgeon_schedule(
    db: Session,
    *,
    surgeons: list[dict[str, Any]],
    source: str = "desk",
    source_fax_id: int | None = None,
    source_message_id: str | None = None,
    notify: bool = False,
) -> dict[str, Any]:
    """Publish parsed Desk surgeon blocks into CAL Block OR + cases + clinic lanes."""
    created_blocks: list[dict] = []
    case_results: list[dict] = []
    created_clinics: list[dict] = []
    flags: list[dict] = []
    errors: list[dict] = []

    note_bits = []
    # Keep fax provenance in audit/flags only — not in human-facing OR notes.
    base_note = ""
    if source_fax_id:
        # Internal-only tag for re-ingest matching; stripped before native/portal display.
        base_note = f"Desk fax #{source_fax_id}"

    for idx, block in enumerate(surgeons):
        surgeon = resolve_surgeon(db, block.get("surgeon_name") or block.get("surgeon_raw"))
        if not surgeon:
            errors.append({
                "index": idx,
                "error": f"surgeon not found: {block.get('surgeon_name') or block.get('surgeon_raw')}",
            })
            continue

        or_block = block.get("or_block") or {}
        cases = list(or_block.get("cases") or [])
        session = (or_block.get("session") or "am").lower()

        by_date: dict[date, list[dict]] = defaultdict(list)
        for case in cases:
            day = _parse_date(case.get("case_date") or block.get("start_date"))
            if not day or not (case.get("patient_name") or "").strip():
                errors.append({
                    "index": idx,
                    "patient_name": case.get("patient_name"),
                    "error": "OR case missing date or patient_name",
                })
                continue
            by_date[day].append(case)

        # Only days with OR cases (plus empty days inside a declared OR window) are
        # authoritative. Clinic-only surgeon blocks must not cancel OR inventory.
        authority_days: list[date] = []
        if by_date:
            range_start = _parse_date(block.get("start_date"))
            range_end = _parse_date(block.get("end_date")) or range_start
            range_start = min([d for d in [range_start, *by_date.keys()] if d is not None])
            range_end = max([d for d in [range_end, *by_date.keys()] if d is not None])
            cursor = range_start
            while cursor <= range_end:
                authority_days.append(cursor)
                cursor += timedelta(days=1)

        for day in authority_days:
            day_cases = by_date.get(day, [])
            claimed_ids: set[int] = set()
            day_candidates = (
                db.query(SurgicalCase)
                .filter(
                    SurgicalCase.surgeon_id == surgeon.id,
                    SurgicalCase.date == day,
                    SurgicalCase.status != "cancelled",
                )
                .order_by(SurgicalCase.start_time, SurgicalCase.id)
                .all()
            )

            if not day_cases:
                case_results.extend(
                    _cancel_missing_desk_cases(
                        db,
                        surgeon_id=surgeon.id,
                        case_date=day,
                        claimed_ids=claimed_ids,
                    )
                )
                continue

            room = (
                day_cases[0].get("room")
                or or_block.get("room")
                or (or_block.get("rooms") or [None])[0]
            )
            loc = resolve_or_location(
                db,
                room,
                surgeon_id=surgeon.id,
                day=day,
                session=session,
            )
            if not loc:
                errors.append({
                    "index": idx,
                    "date": day.isoformat(),
                    "error": f"OR location not found for room: {room}",
                })
                continue

            try:
                start_t, end_t = _block_window_for_cases(
                    day_cases,
                    session,
                    or_block.get("block_start") or or_block.get("start_time"),
                    or_block.get("block_end") or or_block.get("end_time"),
                )
                instance, block_action = _ensure_or_block_for_fax(
                    db,
                    block_date=day,
                    location_id=loc.id,
                    start_time=start_t,
                    end_time=end_t,
                    session=session,
                    notes=base_note,
                    room_text=room,
                )
                # Re-read window after possible expansion (fax SSOT fitted into inventory).
                start_t, end_t = instance.start_time, instance.end_time
                parsed_starts = [_parse_time(c.get("start_time"), start_t) for c in day_cases]
                earliest = min([t for t in parsed_starts if t is not None], default=start_t)
                warnings = _assign_surgeon_to_block(
                    db,
                    block=instance,
                    surgeon_id=surgeon.id,
                    assigned_start=earliest,
                    case_count=len(day_cases),
                    base_note=base_note,
                )
                if warnings:
                    flags.append({
                        "surgeon_id": surgeon.id,
                        "date": day.isoformat(),
                        "block_id": instance.id,
                        "location": loc.abbreviation or loc.name,
                        "warnings": warnings,
                    })
                _flag_admin_schedule_issues(
                    db,
                    surgeon_id=surgeon.id,
                    surgeon_name=surgeon.full_name,
                    day=day,
                    block=instance,
                    location_label=loc.abbreviation or loc.name or "OR",
                    warnings=warnings,
                    fax_note=base_note,
                )
                created_blocks.append({
                    "block_id": instance.id,
                    "action": block_action,
                    "date": day.isoformat(),
                    "location": loc.abbreviation or loc.name,
                    "start": start_t.strftime("%H:%M"),
                    "end": end_t.strftime("%H:%M"),
                    "surgeon_id": surgeon.id,
                    "case_count": len(day_cases),
                    "warnings": warnings,
                })
                for case in day_cases:
                    st = _parse_time(case.get("start_time"), earliest)
                    if st is None:
                        continue
                    case_results.append(
                        _upsert_surgical_case(
                            db,
                            surgeon_id=surgeon.id,
                            case_date=day,
                            start_time=st,
                            patient_name=case["patient_name"],
                            procedure=case.get("procedure") or "TBD",
                            location_id=loc.id,
                            room_text=case.get("room") or room or "",
                            notes=base_note,
                            or_block_instance_id=instance.id,
                            notify=notify,
                            day_candidates=day_candidates,
                            claimed_ids=claimed_ids,
                        )
                    )
                case_results.extend(
                    _cancel_missing_desk_cases(
                        db,
                        surgeon_id=surgeon.id,
                        case_date=day,
                        claimed_ids=claimed_ids,
                    )
                )
            except Exception as exc:  # noqa: BLE001 — per-day isolation
                errors.append({
                    "index": idx,
                    "date": day.isoformat(),
                    "error": str(exc),
                })

        clinic = block.get("clinic_rotation") or {}
        slots = list(clinic.get("slots") or [])
        clinic_session = (clinic.get("session") or "pm").lower()
        site = clinic.get("site_raw") or (slots[0].get("site_raw") if slots else None)

        clinic_by_date: dict[date, list[dict]] = defaultdict(list)
        for slot in slots:
            day = _parse_date(slot.get("case_date") or block.get("start_date"))
            if day:
                clinic_by_date[day].append(slot)
        # Only touch clinic lanes when the fax actually has clinic data (SSOT).
        if not clinic_by_date and site:
            day = _parse_date(block.get("start_date"))
            if day:
                clinic_by_date[day] = []

        for day, day_slots in sorted(clinic_by_date.items()):
            site_for_day = (day_slots[0].get("site_raw") if day_slots else None) or site
            loc = resolve_clinic_location(
                db,
                site_for_day,
                surgeon_id=surgeon.id,
                day=day,
                session=clinic_session,
            )
            if not loc:
                errors.append({
                    "index": idx,
                    "date": day.isoformat(),
                    "error": f"clinic location not found for site: {site_for_day}",
                })
                continue
            time_bits = []
            for slot in sorted(day_slots, key=lambda s: s.get("start_time") or ""):
                t = (slot.get("start_time") or "").strip()
                name = (slot.get("patient_name") or "").strip()
                if t or name:
                    time_bits.append(f"{t} {name}".strip())
            notes = base_note
            if time_bits:
                notes = f"{base_note} · " + "; ".join(time_bits[:12])
            try:
                created_clinics.append(
                    _upsert_clinic_day(
                        db,
                        surgeon_id=surgeon.id,
                        day=day,
                        session=clinic_session,
                        location_id=loc.id,
                        notes=notes,
                    )
                )
            except Exception as exc:  # noqa: BLE001
                errors.append({
                    "index": idx,
                    "date": day.isoformat(),
                    "error": f"clinic: {exc}",
                })

    def _count(action: str) -> int:
        return sum(1 for row in case_results if row.get("action") == action)

    return {
        "ok": len(errors) == 0,
        "blocks": created_blocks,
        "blocks_count": len(created_blocks),
        "cases": case_results,
        "cases_count": len(case_results),
        "cases_created": _count("created"),
        "cases_updated": _count("updated"),
        "cases_unchanged": _count("unchanged"),
        "cases_removed": _count("removed"),
        "clinics": created_clinics,
        "clinics_count": len(created_clinics),
        "flags": flags,
        "flags_count": len(flags),
        # created_count kept for Desk handoff UI; now means net new cases only.
        "created_count": _count("created"),
        "error_count": len(errors),
        "errors": errors,
        "created": case_results,
    }
