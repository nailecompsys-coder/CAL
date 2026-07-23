"""Desk → CAL schedule ingest: Block OR capacity + surgical cases + clinic day lanes.

OR fax times become Block OR windows (practice capacity) with cases under them.
Clinic fax times become ClinicSchedule day/session assignments (notes carry clock times
until ClinicSchedule has real start/end columns).
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, time, timedelta
from typing import Any

from sqlalchemy.orm import Session

from .admin_surgical_schedule_service import add_surgical_case
from .ingest_resolve import resolve_clinic_location, resolve_or_location, resolve_surgeon
from .models import ClinicSchedule, ORBlockInstance, SurgicalCase
from .or_block_service import (
    BlockORCreateInput,
    assign_block,
    create_or_blocks,
    overlapping_or_blocks,
    parse_hhmm,
    session_default_times,
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
    """Case clocks define the block window; fall back to AM/PM session defaults."""
    default_start, default_end = session_default_times(session or "am")
    start = _parse_time(explicit_start)
    end = _parse_time(explicit_end)
    times = [t for t in (_parse_time(c.get("start_time")) for c in cases) if t is not None]
    if start is None and times:
        start = min(times)
    if end is None and times:
        latest = max(times)
        end = (datetime.combine(date.today(), latest) + timedelta(minutes=90)).time()
    if start is None:
        start = default_start
    if end is None:
        end = default_end
    if start >= end:
        end = (datetime.combine(date.today(), start) + timedelta(hours=4)).time()
    return start, end


def _find_or_reuse_block(
    db: Session,
    *,
    block_date: date,
    location_id: int,
    start_time: time,
    end_time: time,
    session: str,
    notes: str,
) -> ORBlockInstance:
    overlaps = overlapping_or_blocks(
        db,
        block_date=block_date,
        location_id=location_id,
        start_time=start_time,
        end_time=end_time,
    )
    if overlaps:
        return overlaps[0]
    created = create_or_blocks(
        db,
        BlockORCreateInput(
            name=f"Desk OR {block_date.isoformat()}",
            start_date=block_date,
            end_date=block_date,
            weekdays=[block_date.weekday()],
            location_ids=[location_id],
            session=session if session in {"am", "pm", "both", "custom"} else "am",
            start_time=start_time,
            end_time=end_time,
            recurrence="once",
            notes=notes,
        ),
        admin_id=None,
    )
    block = db.get(ORBlockInstance, created["instance_ids"][0])
    if not block:
        raise ValueError("Failed to create Block OR instance")
    return block


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
) -> dict[str, Any]:
    existing = (
        db.query(SurgicalCase)
        .filter(
            SurgicalCase.surgeon_id == surgeon_id,
            SurgicalCase.date == case_date,
            SurgicalCase.start_time == start_time,
            SurgicalCase.patient_name == patient_name.strip(),
            SurgicalCase.status != "cancelled",
        )
        .first()
    )
    if existing:
        existing.procedure = procedure or existing.procedure
        existing.location_id = location_id or existing.location_id
        existing.room_text = room_text or existing.room_text
        existing.notes = notes or existing.notes
        if or_block_instance_id:
            existing.or_block_instance_id = or_block_instance_id
        db.commit()
        return {
            "id": existing.id,
            "action": "updated",
            "case_date": case_date.isoformat(),
            "patient_name": existing.patient_name,
            "start_time": start_time.strftime("%H:%M"),
        }

    fields = {
        "surgeon_id": surgeon_id,
        "date": case_date,
        "start_time": start_time,
        "end_time": None,
        "patient_name": patient_name.strip(),
        "patient_dob": None,
        "patient_phone": None,
        "procedure": (procedure or "TBD").strip(),
        "location_id": location_id,
        "room_text": room_text.strip() or None,
        "status": "scheduled",
        "notes": notes.strip() or None,
        "or_block_instance_id": or_block_instance_id,
    }
    surgical_case, _warn = add_surgical_case(db, fields, notify=notify)
    return {
        "id": surgical_case.id,
        "action": "created",
        "case_date": case_date.isoformat(),
        "patient_name": surgical_case.patient_name,
        "start_time": start_time.strftime("%H:%M"),
    }


def _upsert_clinic_day(
    db: Session,
    *,
    surgeon_id: int,
    day: date,
    session: str,
    location_id: int,
    notes: str,
) -> dict[str, Any]:
    """Write clinic lane without staff push spam (bulk fax ingest)."""
    sess = (session or "pm").lower()
    if sess not in {"am", "pm", "full"}:
        sess = "pm"
    slot_q = db.query(ClinicSchedule).filter(
        ClinicSchedule.surgeon_id == surgeon_id,
        ClinicSchedule.date == day,
    )
    for existing in list(slot_q.filter(ClinicSchedule.session.in_([sess, "full"])).all()):
        db.delete(existing)
    db.flush()
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
    created_cases: list[dict] = []
    created_clinics: list[dict] = []
    errors: list[dict] = []

    note_bits = []
    if source_fax_id:
        note_bits.append(f"Desk fax #{source_fax_id}")
    if source_message_id:
        note_bits.append(f"Kno2 {source_message_id}")
    note_bits.append(f"source={source}")
    base_note = " · ".join(note_bits)

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

        for day, day_cases in sorted(by_date.items()):
            room = (
                day_cases[0].get("room")
                or or_block.get("room")
                or (or_block.get("rooms") or [None])[0]
            )
            loc = resolve_or_location(db, room)
            if not loc:
                errors.append({
                    "index": idx,
                    "date": day.isoformat(),
                    "error": f"OR location not found for room: {room}",
                })
                continue

            start_t, end_t = _block_window_for_cases(
                day_cases,
                session,
                or_block.get("block_start") or or_block.get("start_time"),
                or_block.get("block_end") or or_block.get("end_time"),
            )
            try:
                instance = _find_or_reuse_block(
                    db,
                    block_date=day,
                    location_id=loc.id,
                    start_time=start_t,
                    end_time=end_t,
                    session=session,
                    notes=base_note,
                )
                parsed_starts = [_parse_time(c.get("start_time"), start_t) for c in day_cases]
                earliest = min([t for t in parsed_starts if t is not None], default=start_t)
                try:
                    assign_block(
                        db,
                        instance.id,
                        surgeon.id,
                        admin_id=None,
                        assigned_start_time=earliest,
                        case_count=len(day_cases),
                        assignment_note=base_note + " · fax schedule override",
                    )
                except ValueError as exc:
                    if "already assigned" not in str(exc).lower():
                        raise
                created_blocks.append({
                    "block_id": instance.id,
                    "date": day.isoformat(),
                    "location": loc.abbreviation or loc.name,
                    "start": start_t.strftime("%H:%M"),
                    "end": end_t.strftime("%H:%M"),
                    "surgeon_id": surgeon.id,
                    "case_count": len(day_cases),
                })
                for case in day_cases:
                    st = _parse_time(case.get("start_time"), earliest)
                    if st is None:
                        continue
                    created_cases.append(
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
        clinic_loc = resolve_clinic_location(db, site) if site else None

        clinic_by_date: dict[date, list[dict]] = defaultdict(list)
        for slot in slots:
            day = _parse_date(slot.get("case_date") or block.get("start_date"))
            if day:
                clinic_by_date[day].append(slot)
        if not clinic_by_date and clinic_loc:
            day = _parse_date(block.get("start_date"))
            if day:
                clinic_by_date[day] = []

        for day, day_slots in sorted(clinic_by_date.items()):
            loc = clinic_loc or resolve_clinic_location(
                db, (day_slots[0].get("site_raw") if day_slots else None) or site
            )
            if not loc:
                errors.append({
                    "index": idx,
                    "date": day.isoformat(),
                    "error": f"clinic location not found for site: {site}",
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

    return {
        "ok": len(errors) == 0,
        "blocks": created_blocks,
        "blocks_count": len(created_blocks),
        "cases": created_cases,
        "cases_count": len(created_cases),
        "clinics": created_clinics,
        "clinics_count": len(created_clinics),
        "created_count": len(created_cases),
        "error_count": len(errors),
        "errors": errors,
        "created": created_cases,
    }
