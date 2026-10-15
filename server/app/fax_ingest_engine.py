"""Staging-only Desk/LlamaParse intake for the permanent card scaffold.

This module has deliberately no imports from legacy schedule writers, email,
SMS, notifications, or OR block assignment code. It records reviewed Desk
facts and resolves each row to an already-existing AM/PM card for review.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date, time

from sqlalchemy import or_, text
from sqlalchemy.orm import Session

from .models import (
    FaxDocument,
    FaxIngestRow,
    FaxIngestRun,
    FaxRowDecision,
    Location,
    ORBlockAssignment,
    ORBlockInstance,
    ScheduleCard,
    Surgeon,
)


ENGINE_VERSION = "fax-png-stage-v1"


@dataclass(frozen=True)
class ReviewedFaxRow:
    page: int
    surgeon_initials: str
    surgeon_name: str | None
    case_date: date
    start_time: time | None
    row_type: str
    room: str
    patient_name: str
    procedure: str = ""
    extraction_flags: str | None = None


@dataclass
class _PreparedRow:
    row: ReviewedFaxRow
    surgeon: Surgeon | None
    session: str
    source_location: Location | None
    card: ScheduleCard | None


def mark_fax_ingest_transaction(db: Session, run_id: int | None = None) -> None:
    """Postgres triggers reject AM/PM block writes for the rest of this transaction."""
    if db.bind.dialect.name != "postgresql":
        return
    db.execute(
        text("SELECT set_config('cal.writer', 'fax_ingest', true), set_config('cal.fax_run_id', :run_id, true)"),
        {"run_id": str(run_id or "")},
    )


def session_for_time(value: time | None) -> str:
    return "am" if value is not None and value < time(12) else "pm"


def sessions_for_rows(rows: list[ReviewedFaxRow]) -> list[str]:
    """Resolve AM/PM with the documented clinic-to-OR transition rule.

    Noon remains the normal boundary. A surgical case between 11:30 and noon
    moves to PM only when that surgeon has a clinic appointment earlier that
    day and the gap is at least 30 minutes. This keeps an 11:45 downstairs OR
    start after an 11:00 clinic visit out of the AM clinic card.
    """
    resolved = [session_for_time(row.start_time) for row in rows]
    clinic_times: dict[tuple[str, date], list[time]] = {}
    for row in rows:
        if row.row_type != "clinic" or row.start_time is None:
            continue
        key = (_normal(row.surgeon_name or row.surgeon_initials), row.case_date)
        clinic_times.setdefault(key, []).append(row.start_time)

    for index, row in enumerate(rows):
        if row.row_type != "surgical" or row.start_time is None:
            continue
        if not time(11, 30) <= row.start_time < time(12):
            continue
        key = (_normal(row.surgeon_name or row.surgeon_initials), row.case_date)
        prior = [value for value in clinic_times.get(key, []) if value < row.start_time]
        if not prior:
            continue
        gap = (
            row.start_time.hour * 60
            + row.start_time.minute
            - max(value.hour * 60 + value.minute for value in prior)
        )
        if gap >= 30:
            resolved[index] = "pm"
    return resolved


def _text(value: str | None) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def _normal(value: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (value or "").lower()).strip()


def _fitted_blocks(db: Session, surgeon_id: int, day: date, at_time: time) -> list[ORBlockInstance]:
    """Blocks whose clock contains this case for this surgeon."""
    rows = (
        db.query(ORBlockInstance)
        .outerjoin(
            ORBlockAssignment,
            ORBlockAssignment.block_instance_id == ORBlockInstance.id,
        )
        .filter(
            ORBlockInstance.date == day,
            ORBlockInstance.status.in_(("open", "assigned")),
            ORBlockInstance.start_time <= at_time,
            ORBlockInstance.end_time > at_time,
            or_(
                ORBlockInstance.assigned_surgeon_id == surgeon_id,
                ORBlockAssignment.surgeon_id == surgeon_id,
            ),
        )
        .all()
    )
    return list({row.id: row for row in rows}.values())


def _facility_for_case(
    db: Session,
    surgeon_id: int | None,
    day: date,
    at_time: time | None,
    card: ScheduleCard | None,
) -> tuple[Location | None, str]:
    """The hospital is the block the case fits. The room text is not a hospital."""
    if surgeon_id and at_time is not None:
        blocks = _fitted_blocks(db, surgeon_id, day, at_time)
        location_ids = {block.location_id for block in blocks if block.location_id}
        if len(location_ids) > 1:
            return None, "unclear"
        if len(location_ids) == 1:
            return db.get(Location, next(iter(location_ids))), "block"
    if card and card.baseline_state == "assigned" and card.baseline_location_id:
        return card.baseline_location, "card"
    return None, "none"


def _surgeon_for_row(db: Session, row: ReviewedFaxRow) -> Surgeon | None:
    initials = _text(row.surgeon_initials).upper()
    candidates = [
        surgeon for surgeon in db.query(Surgeon).filter(Surgeon.is_active == True).all()  # noqa: E712
        if f"{(surgeon.first_name or '')[:1]}{(surgeon.last_name or '')[:1]}".upper() == initials
    ]
    if len(candidates) == 1:
        return candidates[0]
    if row.surgeon_name:
        wanted = _normal(row.surgeon_name)
        named = [surgeon for surgeon in candidates if _normal(surgeon.full_name) == wanted]
        if len(named) == 1:
            return named[0]
    return None


def _key(row: ReviewedFaxRow) -> str:
    clock = row.start_time.strftime("%H:%M") if row.start_time else ""
    return "|".join((_normal(row.surgeon_name or row.surgeon_initials), row.case_date.isoformat(), clock, row.row_type, _normal(row.patient_name)))


def stage_reviewed_rows(
    db: Session,
    *,
    external_fax_id: int,
    source_label: str,
    rows: list[ReviewedFaxRow],
    surgeon_scope: list[str] | None = None,
) -> dict:
    """Persist reviewed fax facts and deterministic, non-mutating card decisions."""
    if not rows:
        raise ValueError("rows required")
    mark_fax_ingest_transaction(db)
    document = db.query(FaxDocument).filter(FaxDocument.external_fax_id == external_fax_id).one_or_none()
    if document is None:
        document = FaxDocument(external_fax_id=external_fax_id, source_label=_text(source_label) or "Desk LlamaParse extraction")
        db.add(document)
        db.flush()
    scope = sorted({value.strip().upper() for value in (surgeon_scope or []) if value.strip()})
    if not scope:
        scope = sorted({_text(row.surgeon_initials).upper() for row in rows if _text(row.surgeon_initials)})
    run = FaxIngestRun(
        fax_document_id=document.id,
        engine_version=ENGINE_VERSION,
        status="staged",
        surgeon_scope_json=json.dumps(scope),
    )
    db.add(run)
    db.flush()

    counts: dict[str, int] = {}
    resolved_sessions = sessions_for_rows(rows)
    prepared: list[_PreparedRow] = []
    for row, resolved_session in zip(rows, resolved_sessions, strict=True):
        if row.row_type not in {"surgical", "clinic"}:
            raise ValueError("row_type must be surgical or clinic")
        surgeon = _surgeon_for_row(db, row)
        card = None
        if surgeon:
            card = db.query(ScheduleCard).filter(
                ScheduleCard.surgeon_id == surgeon.id,
                ScheduleCard.date == row.case_date,
                ScheduleCard.session == resolved_session,
            ).one_or_none()
        source_location, _kind = _facility_for_case(
            db,
            surgeon.id if surgeon else None,
            row.case_date,
            row.start_time,
            card,
        )
        prepared.append(_PreparedRow(row, surgeon, resolved_session, source_location, card))

    for item in prepared:
        row = item.row
        room = _text(row.room).upper()
        flags = [value for value in (_text(row.extraction_flags),) if value]
        staged = FaxIngestRow(
            run_id=run.id,
            page_number=row.page,
            surgeon_id=item.surgeon.id if item.surgeon else None,
            surgeon_initials=_text(row.surgeon_initials).upper(),
            case_date=row.case_date,
            start_time=row.start_time,
            session=item.session,
            row_type=row.row_type,
            room_text=room,
            patient_name=_text(row.patient_name),
            procedure=_text(row.procedure),
            source_location_id=item.source_location.id if item.source_location else None,
            normalized_key=_key(row),
            extraction_flags="; ".join(flags) or None,
        )
        db.add(staged)
        db.flush()
        decision = _decide(db, staged)
        db.add(decision)
        counts[decision.status] = counts.get(decision.status, 0) + 1
    db.flush()
    return {"faxDocumentId": document.id, "runId": run.id, "rows": len(rows), "decisions": counts, "writeMode": "staging_only"}


def _decide(db: Session, row: FaxIngestRow) -> FaxRowDecision:
    if row.extraction_flags:
        return FaxRowDecision(fax_row_id=row.id, status="needs_review", reason_code="extraction_flagged", detail=f"Desk flagged this row: {row.extraction_flags}")
    if not row.surgeon_id:
        return FaxRowDecision(fax_row_id=row.id, status="needs_review", reason_code="unknown_surgeon", detail="No unique active surgeon matched the fax row.")
    card = db.query(ScheduleCard).filter(
        ScheduleCard.surgeon_id == row.surgeon_id,
        ScheduleCard.date == row.case_date,
        ScheduleCard.session == row.session,
    ).one_or_none()
    if not card:
        return FaxRowDecision(fax_row_id=row.id, status="needs_review", reason_code="missing_scaffold", detail="Permanent AM/PM card is missing; ingest is not allowed to create one.")
    if card.effective_state == "off":
        return FaxRowDecision(fax_row_id=row.id, schedule_card_id=card.id, status="needs_review", reason_code="off_collision", detail="Fax activity is preserved for review against approved OFF.")
    _location, kind = _facility_for_case(db, row.surgeon_id, row.case_date, row.start_time, card)
    if kind == "unclear":
        return FaxRowDecision(
            fax_row_id=row.id,
            schedule_card_id=card.id,
            status="needs_review",
            reason_code="block_facility_unclear",
            detail="More than one block fits this time, so the hospital is not chosen from the room.",
        )
    if kind == "none":
        return FaxRowDecision(
            fax_row_id=row.id,
            schedule_card_id=card.id,
            status="needs_review",
            reason_code="no_block_for_facility",
            detail="No block fits this time, and the room name is not a hospital.",
        )
    if kind == "block" and card.baseline_location_id and row.source_location_id != card.baseline_location_id:
        return FaxRowDecision(
            fax_row_id=row.id,
            schedule_card_id=card.id,
            status="ready",
            reason_code="epic_override",
            detail="The block this case fits is a different hospital from the master card.",
        )
    if kind == "block" and card.effective_state == "na":
        return FaxRowDecision(
            fax_row_id=row.id,
            schedule_card_id=card.id,
            status="ready",
            reason_code="block_location",
            detail="The hospital comes from the block this case fits.",
        )
    detail = "Ready to attach to the existing permanent card; no card or baseline will be changed."
    return FaxRowDecision(fax_row_id=row.id, schedule_card_id=card.id, status="ready", reason_code="existing_card", detail=detail)
