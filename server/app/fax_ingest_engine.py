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

from sqlalchemy import text
from sqlalchemy.orm import Session

from .models import FaxDocument, FaxIngestRow, FaxIngestRun, FaxRowDecision, Location, ScheduleCard, Surgeon


ENGINE_VERSION = "fax-png-stage-v1"

ROOM_LOCATION_ABBREVIATIONS = {
    "ALT": "AL-OR", "AL": "AL-OR", "APK": "AP-OR", "AP": "AP-OR",
    "MIN": "MN-OR", "MN": "MN-OR", "WGD": "WG-OR", "WG": "WG-OR",
    "CLMMFLGS": "CL-OV", "MGALTGS": "AL-OV", "MGWGDGS": "WG-OV", "MGWGDS": "WG-OV",
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


def _minutes(value: time | None) -> int:
    return value.hour * 60 + value.minute if value else 24 * 60


def _location_matches_row_type(location: Location, row_type: str) -> bool:
    abbreviation = (location.abbreviation or "").upper()
    if row_type == "surgical":
        return abbreviation.endswith("-OR") or (location.location_type or "").lower() in {"hospital", "or"}
    return abbreviation.endswith("-OV") or (location.location_type or "").lower() == "clinic"


def _infer_generic_group_location(group: list[_PreparedRow], prepared: list[_PreparedRow]) -> Location | None:
    """Resolve a generic room into an existing NA card from same-day evidence.

    AHMGGENSRG is a placeholder, not a facility. The fax still provides the
    surgeon, date, session, time sequence, and row type. Prefer a location
    already assigned to the target card, then explicit activity in the same
    session, then the nearest prior compatible same-day activity.
    """
    row_type_counts = {
        row_type: sum(item.row.row_type == row_type for item in group)
        for row_type in {item.row.row_type for item in group}
    }
    dominant_type = max(row_type_counts, key=row_type_counts.get)
    if list(row_type_counts.values()).count(row_type_counts[dominant_type]) > 1:
        return None

    surgeon_id = group[0].surgeon.id if group[0].surgeon else None
    day = group[0].row.case_date
    session = group[0].session
    candidates = [
        item for item in prepared
        if item.surgeon
        and item.surgeon.id == surgeon_id
        and item.row.case_date == day
        and item.source_location
        and _location_matches_row_type(item.source_location, dominant_type)
    ]
    same_session = [item for item in candidates if item.session == session]
    if same_session:
        candidates = same_session
    else:
        card = group[0].card
        if card and card.baseline_location:
            return card.baseline_location
        if not candidates:
            return card.effective_location if card and card.effective_location else None

    first_group_minute = min(_minutes(item.row.start_time) for item in group)
    prior = [item for item in candidates if _minutes(item.row.start_time) <= first_group_minute]
    pool = prior or candidates
    best_minute = (
        max(_minutes(item.row.start_time) for item in pool)
        if prior
        else min(_minutes(item.row.start_time) for item in pool)
    )
    nearest = [item for item in pool if _minutes(item.row.start_time) == best_minute]
    location_ids = {item.source_location.id for item in nearest if item.source_location}
    if len(location_ids) != 1:
        return None
    return nearest[0].source_location


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
        room = _text(row.room).upper()
        source_location = _room_location(db, room)
        card = None
        if surgeon:
            card = db.query(ScheduleCard).filter(
                ScheduleCard.surgeon_id == surgeon.id,
                ScheduleCard.date == row.case_date,
                ScheduleCard.session == resolved_session,
            ).one_or_none()
        prepared.append(_PreparedRow(row, surgeon, resolved_session, source_location, card))

    generic_groups: dict[tuple[int | None, date, str, str], list[_PreparedRow]] = {}
    for item in prepared:
        room = _text(item.row.room).upper()
        if room not in GENERIC_LOCATION_ROOMS or item.source_location:
            continue
        key = (item.surgeon.id if item.surgeon else None, item.row.case_date, item.session, room)
        generic_groups.setdefault(key, []).append(item)
    for group in generic_groups.values():
        inferred = _infer_generic_group_location(group, prepared)
        if inferred:
            for item in group:
                item.source_location = inferred

    # A room code CAL does not know is read off the surgeon's AM/PM card.
    unknown_room: set[int] = set()
    row_types: dict[int, str] = {}
    for index, item in enumerate(prepared):
        room = _text(item.row.room).upper()
        if not room or room in GENERIC_LOCATION_ROOMS or item.source_location:
            continue
        card = item.card
        if card and card.baseline_state == "assigned" and card.baseline_location:
            item.source_location = card.baseline_location
            row_types[index] = "surgical" if _location_matches_row_type(card.baseline_location, "surgical") else "clinic"
        else:
            unknown_room.add(index)

    for index, item in enumerate(prepared):
        row = item.row
        room = _text(row.room).upper()
        flags = [value for value in (_text(row.extraction_flags), "unknown_room" if index in unknown_room else "") if value]
        staged = FaxIngestRow(
            run_id=run.id,
            page_number=row.page,
            surgeon_id=item.surgeon.id if item.surgeon else None,
            surgeon_initials=_text(row.surgeon_initials).upper(),
            case_date=row.case_date,
            start_time=row.start_time,
            session=item.session,
            row_type=row_types.get(index, row.row_type),
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
    if row.room_text in GENERIC_LOCATION_ROOMS and card.effective_state == "na" and not row.source_location_id:
        return FaxRowDecision(fax_row_id=row.id, schedule_card_id=card.id, status="needs_review", reason_code="generic_room_on_na", detail="Generic room has no facility evidence and the card is NA.")
    if row.source_location_id and card.baseline_location_id and row.source_location_id != card.baseline_location_id:
        return FaxRowDecision(
            fax_row_id=row.id,
            schedule_card_id=card.id,
            status="ready",
            reason_code="epic_override",
            detail="EPIC activity differs from the master assignment and will overlay the existing card.",
        )
    if row.room_text in GENERIC_LOCATION_ROOMS and card.effective_state == "na" and row.source_location_id:
        return FaxRowDecision(
            fax_row_id=row.id,
            schedule_card_id=card.id,
            status="ready",
            reason_code="na_context_location",
            detail="Generic EPIC activity was resolved from same-day surgeon and location evidence.",
        )
    detail = "Ready to attach to the existing permanent card; no card or baseline will be changed."
    return FaxRowDecision(fax_row_id=row.id, schedule_card_id=card.id, status="ready", reason_code="existing_card", detail=detail)
