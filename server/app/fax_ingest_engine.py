"""Staging-only fax intake for the permanent schedule-card scaffold.

This module has deliberately no imports from legacy schedule writers, email,
SMS, notifications, or OR block assignment code. It records reviewed PNG/OCR
facts and resolves each row to an already-existing AM/PM card for review.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date, time

from sqlalchemy.orm import Session

from .models import FaxDocument, FaxIngestRow, FaxIngestRun, FaxRowDecision, Location, ScheduleCard, Surgeon


ENGINE_VERSION = "fax-png-stage-v1"

ROOM_LOCATION_ABBREVIATIONS = {
    "ALT": "AL-OR", "AL": "AL-OR", "APK": "AP-OR", "AP": "AP-OR",
    "MIN": "MN-OR", "MN": "MN-OR", "WGD": "WG-OR", "WG": "WG-OR",
    "CLMMFLGS": "CL-OV", "MGALTGS": "AL-OV", "MGWGDGS": "WG-OV",
}
GENERIC_LOCATION_ROOMS = {"AHMGGENSRG", "AHMGGENSURG", "MGLKMGENSRG", "MGLKMGENSURG"}


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


def _room_location(db: Session, room: str) -> Location | None:
    normalized = _text(room).upper()
    if normalized in GENERIC_LOCATION_ROOMS:
        return None
    token = normalized.split(" ", 1)[0] if normalized else ""
    abbreviation = ROOM_LOCATION_ABBREVIATIONS.get(normalized) or ROOM_LOCATION_ABBREVIATIONS.get(token)
    if not abbreviation:
        return None
    return db.query(Location).filter(Location.abbreviation == abbreviation).one_or_none()


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
    document = db.query(FaxDocument).filter(FaxDocument.external_fax_id == external_fax_id).one_or_none()
    if document is None:
        document = FaxDocument(external_fax_id=external_fax_id, source_label=_text(source_label) or "Desk visual PNG SOT")
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
    for row, resolved_session in zip(rows, resolved_sessions, strict=True):
        if row.row_type not in {"surgical", "clinic"}:
            raise ValueError("row_type must be surgical or clinic")
        surgeon = _surgeon_for_row(db, row)
        room = _text(row.room).upper()
        source_location = _room_location(db, room)
        staged = FaxIngestRow(
            run_id=run.id,
            page_number=row.page,
            surgeon_id=surgeon.id if surgeon else None,
            surgeon_initials=_text(row.surgeon_initials).upper(),
            case_date=row.case_date,
            start_time=row.start_time,
            session=resolved_session,
            row_type=row.row_type,
            room_text=room,
            patient_name=_text(row.patient_name),
            procedure=_text(row.procedure),
            source_location_id=source_location.id if source_location else None,
            normalized_key=_key(row),
        )
        db.add(staged)
        db.flush()
        decision = _decide(db, staged)
        db.add(decision)
        counts[decision.status] = counts.get(decision.status, 0) + 1
    db.flush()
    return {"faxDocumentId": document.id, "runId": run.id, "rows": len(rows), "decisions": counts, "writeMode": "staging_only"}


def _decide(db: Session, row: FaxIngestRow) -> FaxRowDecision:
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
    if row.source_location_id and card.effective_location_id and row.source_location_id != card.effective_location_id:
        return FaxRowDecision(fax_row_id=row.id, schedule_card_id=card.id, status="needs_review", reason_code="location_mismatch", detail="Fax room location does not match the permanent card baseline.")
    if row.room_text in GENERIC_LOCATION_ROOMS and card.effective_state == "na":
        return FaxRowDecision(fax_row_id=row.id, schedule_card_id=card.id, status="needs_review", reason_code="generic_room_on_na", detail="Generic room has no facility evidence and the card is NA.")
    detail = "Ready to attach to the existing permanent card; no card or baseline will be changed."
    return FaxRowDecision(fax_row_id=row.id, schedule_card_id=card.id, status="ready", reason_code="existing_card", detail=detail)
