"""Drag-drop desk ingest corrections: park OCR misfits, place on Block OR, Save."""

from __future__ import annotations

import json
from datetime import date, datetime, time, timedelta
from typing import Any

from sqlalchemy.orm import Session, joinedload

from .admin_schedule_template_clinic_service import week_pattern_matches
from .models import AdminNotification, ClinicSchedule, ORBlockInstance, Surgeon, SurgicalCase, SurgeonLocationSchedule
from .or_block_service import (
    ACTIVE_BLOCK_STATUSES,
    block_instances_for_range,
    serialize_block_instance,
)
from .paper_block_schedule import _place_or_block
from .practice_time import practice_today
from .surgeon_visibility import surgeon_is_visible


def _parse_hhmm(raw: str | None) -> time | None:
    text = (raw or "").strip()
    if not text:
        return None
    try:
        return datetime.strptime(text, "%H:%M").time()
    except ValueError:
        return None


def _us_date_label(value: date | None) -> str:
    if value is None:
        return ""
    return f"{value.month}/{value.day}/{value.year}"


def _session_for_time(value: time | None) -> str | None:
    if value is None:
        return None
    return "am" if value < time(12, 0) else "pm"


def _classify_parked_case(db: Session, case: SurgicalCase) -> dict[str, str]:
    surgeon = case.surgeon
    loc = case.location
    initials = (surgeon.initials or "").strip().upper() if surgeon else ""
    day = case.date
    session = _session_for_time(case.start_time)
    location_abbrev = (loc.abbreviation or loc.name or "").strip().upper() if loc else ""
    if not initials or day is None or session is None:
        return {
            "key": "missing-data",
            "title": "Missing fax data",
            "detail": "Fix this because CAL needs surgeon, date, time, and location before it can place the row.",
        }

    master = db.query(SurgeonLocationSchedule).filter(
        SurgeonLocationSchedule.surgeon_id == case.surgeon_id,
        SurgeonLocationSchedule.day_of_week == day.weekday(),
        SurgeonLocationSchedule.session == session,
    ).first()
    if master is None or not week_pattern_matches(day, master.week_pattern):
        return {
            "key": "blank-master-slot",
            "title": "Blank master slot",
            "detail": (
                f"Fix this because the fax says {initials} has {location_abbrev or 'an OR case'} "
                f"on {_us_date_label(day)} {session.upper()}, but the master schedule is blank."
            ),
        }
    master_abbrev = ((master.location.abbreviation if master.location else "") or "").upper()
    if master_abbrev == location_abbrev:
        return {
            "key": "master-card-missing",
            "title": "Master card missing",
            "detail": (
                f"Fix this because the master schedule says {initials} should have "
                f"{master_abbrev} on {_us_date_label(day)} {session.upper()}, but the card is missing."
            ),
        }
    if master_abbrev.endswith("-OR") and location_abbrev.endswith("-OR"):
        return {
            "key": "wrong-or-location",
            "title": "Facility mismatch",
            "detail": (
                f"Fix this because the fax says {location_abbrev}, but the master schedule says "
                f"{master_abbrev} for {initials} on {_us_date_label(day)} {session.upper()}."
            ),
        }
    return {
        "key": "master-conflict",
        "title": "Master schedule conflict",
        "detail": (
            f"Fix this because the fax says {location_abbrev or 'OR'}, but the master schedule says "
            f"{master_abbrev} for {initials} on {_us_date_label(day)} {session.upper()}."
        ),
    }


def parked_ingest_cases(
    db: Session,
    *,
    start: date | None = None,
    end: date | None = None,
    case_id: int | None = None,
) -> list[dict[str, Any]]:
    """Surgical cases waiting for Block OR placement (OCR misfit limbo)."""
    today = practice_today()
    start = start or (today - timedelta(days=3))
    end = end or (today + timedelta(days=45))
    q = (
        db.query(SurgicalCase)
        .options(
            joinedload(SurgicalCase.surgeon),
            joinedload(SurgicalCase.location),
        )
        .filter(
            SurgicalCase.or_block_instance_id.is_(None),
            SurgicalCase.status != "cancelled",
            SurgicalCase.date >= start,
            SurgicalCase.date <= end,
        )
        .order_by(SurgicalCase.date, SurgicalCase.start_time, SurgicalCase.id)
    )
    if case_id is not None:
        q = (
            db.query(SurgicalCase)
            .options(
                joinedload(SurgicalCase.surgeon),
                joinedload(SurgicalCase.location),
            )
            .filter(SurgicalCase.id == case_id, SurgicalCase.status != "cancelled")
        )
    rows = []
    for case in q.all():
        if case_id is None and case.or_block_instance_id:
            continue
        if case_id is None and case.or_block_instance_id is not None:
            continue
        # Prefer desk-sourced; also include any orphan without a block in range.
        notes = case.notes or ""
        if case_id is None and "Desk fax" not in notes and case.or_block_instance_id is None:
            # Still show orphans — Shannon may have cleared the note.
            pass
        loc = case.location
        surgeon = case.surgeon
        reason = _classify_parked_case(db, case)
        rows.append({
            "id": case.id,
            "date": case.date.isoformat() if case.date else None,
            "dateLabel": _us_date_label(case.date),
            "startTime": case.start_time.strftime("%H:%M") if case.start_time else "",
            "patientName": case.patient_name,
            "procedure": (case.procedure or "")[:80],
            "room": case.room_text or "",
            "location": (loc.abbreviation or loc.name) if loc else "",
            "surgeonId": case.surgeon_id,
            "surgeonName": surgeon.full_name if surgeon else "",
            "surgeonInitials": (surgeon.initials or "") if surgeon else "",
            "notes": notes[:120],
            "needsTime": case.start_time is None,
            "reasonKey": reason["key"],
            "reasonTitle": reason["title"],
            "reasonDetail": reason["detail"],
        })
    return rows


def placement_blocks(
    db: Session,
    *,
    start: date | None = None,
    end: date | None = None,
) -> list[dict[str, Any]]:
    today = practice_today()
    start = start or (today - timedelta(days=3))
    end = end or (today + timedelta(days=21))
    out = []
    for block in block_instances_for_range(db, start, end):
        if (block.status or "") not in ACTIVE_BLOCK_STATUSES:
            continue
        payload = serialize_block_instance(block)
        out.append({
            "id": block.id,
            "date": block.date.isoformat(),
            "session": (block.session or "").upper(),
            "start": block.start_time.strftime("%H:%M") if block.start_time else "",
            "end": block.end_time.strftime("%H:%M") if block.end_time else "",
            "location": (
                payload.get("locationAbbreviation")
                or payload.get("location")
                or ""
            ),
            "room": block.room_text or "",
            "status": block.status,
            "surgeons": [
                {
                    "id": a.get("surgeonId"),
                    "initials": a.get("surgeonInitials") or "",
                    "name": a.get("surgeon") or "",
                }
                for a in (payload.get("assignments") or [])
                if a.get("surgeonId")
            ],
        })
    return out


def surgeons_for_fix(db: Session) -> list[dict[str, Any]]:
    rows = (
        db.query(Surgeon)
        .filter(Surgeon.is_active == True)  # noqa: E712
        .order_by(Surgeon.last_name, Surgeon.first_name)
        .all()
    )
    return [
        {
            "id": s.id,
            "name": s.full_name,
            "initials": s.initials or "",
        }
        for s in rows
        if surgeon_is_visible(s) and (s.staff_type or "physician") == "physician"
    ]


def save_ingest_placements(
    db: Session,
    *,
    placements: list[dict[str, Any]],
    admin_id: int | None = None,
) -> dict[str, Any]:
    """Commit staged drag-drop placements. Clears matching ingest_correction notices."""
    from .models import ORBlockAssignment

    del admin_id
    placed = 0
    errors: list[str] = []
    for raw in placements:
        try:
            case_id = int(raw.get("caseId") or raw.get("case_id"))
            block_id = int(raw.get("blockId") or raw.get("block_id"))
        except (TypeError, ValueError):
            errors.append("Invalid case/block id")
            continue
        case = db.get(SurgicalCase, case_id)
        block = (
            db.query(ORBlockInstance)
            .options(joinedload(ORBlockInstance.location))
            .filter(ORBlockInstance.id == block_id)
            .first()
        )
        if case is None or (case.status or "") == "cancelled":
            errors.append(f"Case {case_id} missing")
            continue
        if block is None or (block.status or "") not in ACTIVE_BLOCK_STATUSES:
            errors.append(f"Block {block_id} missing")
            continue

        surgeon_id = case.surgeon_id
        raw_surgeon = raw.get("surgeonId") or raw.get("surgeon_id")
        if raw_surgeon not in (None, ""):
            try:
                surgeon_id = int(raw_surgeon)
            except (TypeError, ValueError):
                errors.append(f"Bad surgeon for case {case_id}")
                continue

        start = _parse_hhmm(raw.get("startTime") or raw.get("start_time"))
        if start is None:
            start = case.start_time
        if start is None:
            start = block.start_time
        if start is None:
            errors.append(f"Case {case_id} still needs a start time")
            continue

        already = (
            db.query(ORBlockAssignment)
            .filter(
                ORBlockAssignment.block_instance_id == block.id,
                ORBlockAssignment.surgeon_id == surgeon_id,
            )
            .first()
        )
        if already is None:
            errors.append(
                f"Case {case_id}: no existing master OR card for this surgeon/block; parked for review"
            )
            continue

        case.surgeon_id = surgeon_id
        case.date = block.date
        case.start_time = start
        case.or_block_instance_id = block.id
        case.location_id = block.location_id
        if raw.get("room"):
            case.room_text = str(raw.get("room")).strip() or case.room_text

        _clear_case_ingest_notifications(db, case_id=case.id)
        placed += 1

    if placed or errors:
        db.commit()
    return {"ok": not errors, "placed": placed, "errors": errors}


def _clear_case_ingest_notifications(db: Session, *, case_id: int) -> None:
    rows = (
        db.query(AdminNotification)
        .filter(AdminNotification.kind == "ingest_correction")
        .all()
    )
    for row in rows:
        try:
            payload = json.loads(row.payload or "{}") if row.payload else {}
        except (TypeError, ValueError):
            payload = {}
        if payload.get("caseId") in (case_id, str(case_id)):
            db.delete(row)


def dismiss_parked_case(db: Session, *, case_id: int) -> bool:
    case = db.get(SurgicalCase, case_id)
    if case is None:
        return False
    case.status = "cancelled"
    from .schedule_activity_normalization import normalize_surgical_case_card
    normalize_surgical_case_card(db, case)
    _clear_case_ingest_notifications(db, case_id=case_id)
    db.commit()
    return True


def confirm_blank_slot_card(db: Session, *, case_id: int, session: str) -> dict[str, Any]:
    """Explicit scheduler exception: create one dated OR card from a blank slot."""
    case = db.get(SurgicalCase, case_id)
    session = (session or "").lower()
    if case is None or case.status == "cancelled" or session not in {"am", "pm"}:
        return {"ok": False, "reason": "Case or time slot is invalid."}
    if case.location is None or case.location.location_type != "hospital":
        return {"ok": False, "reason": "A blank-slot confirmation requires a hospital OR case."}
    existing = db.query(ClinicSchedule).filter(
        ClinicSchedule.surgeon_id == case.surgeon_id,
        ClinicSchedule.date == case.date,
        ClinicSchedule.session == session,
    ).first()
    if existing is not None:
        return {"ok": False, "reason": "That time slot already has a card."}
    db.add(ClinicSchedule(
        surgeon_id=case.surgeon_id, location_id=case.location_id, date=case.date,
        session=session, assignment_type="assigned", notes="Confirmed blank-slot OR exception",
    ))
    placed = _place_or_block(db, case.surgeon, case.date, session, case.location)
    if placed not in {"assigned", "already"}:
        db.rollback()
        return {"ok": False, "reason": "No OR block could be created for this confirmed slot."}
    result = save_ingest_placements(db, placements=[{"caseId": case.id, "blockId": next(
        row.id for row in db.query(ORBlockInstance).filter(
            ORBlockInstance.date == case.date, ORBlockInstance.location_id == case.location_id
        ).all() if (row.session or "").lower() == session and any(a.surgeon_id == case.surgeon_id for a in row.assignments)
    )}])
    return {"ok": result.get("placed") == 1, "reason": "; ".join(result.get("errors") or [])}
