"""Drag-drop desk ingest corrections: park OCR misfits, place on Block OR, Save."""

from __future__ import annotations

import json
from datetime import date, datetime, time, timedelta
from typing import Any

from sqlalchemy.orm import Session, joinedload

from .models import AdminNotification, ORBlockInstance, Surgeon, SurgicalCase
from .or_block_service import (
    ACTIVE_BLOCK_STATUSES,
    assign_block,
    block_instances_for_range,
    serialize_block_instance,
)
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
        rows.append({
            "id": case.id,
            "date": case.date.isoformat() if case.date else None,
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

        case.surgeon_id = surgeon_id
        case.date = block.date
        case.start_time = start
        case.or_block_instance_id = block.id
        case.location_id = block.location_id
        if raw.get("room"):
            case.room_text = str(raw.get("room")).strip() or case.room_text

        already = (
            db.query(ORBlockAssignment)
            .filter(
                ORBlockAssignment.block_instance_id == block.id,
                ORBlockAssignment.surgeon_id == surgeon_id,
            )
            .first()
        )
        if already is None:
            try:
                assign_block(
                    db,
                    block.id,
                    surgeon_id,
                    admin_id=None,
                    assigned_start_time=min(start, block.end_time) if start < block.end_time else block.start_time,
                    case_count=1,
                    assignment_note="Desk ingest placement",
                    notify=False,
                )
            except Exception as exc:  # noqa: BLE001
                errors.append(f"Case {case_id}: {exc}")
                continue

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
    _clear_case_ingest_notifications(db, case_id=case_id)
    db.commit()
    return True
