"""Apply one reviewed daily fax as the authoritative rolling schedule snapshot."""

from __future__ import annotations

import json
import logging
import re
from collections import defaultdict
from datetime import date
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from .models import (
    FaxDocument,
    FaxIngestRow,
    FaxIngestRun,
    Location,
    ScheduleCard,
    ScheduleChangeEvent,
    Surgeon,
    SurgicalCase,
)
from .fax_ingest_engine import mark_fax_ingest_transaction
from .fax_pdf_intake import cleanup_fax_derivatives, prune_immutable_fax_sources
from .schedule_build_backup_service import create_fax_snapshot_backup
from .fax_source_validation import validate_page_ownership


FAX_NOTE_RE = re.compile(r"\bFax\s+\d+\b", re.IGNORECASE)
logger = logging.getLogger(__name__)


def _normal(value: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", "", (value or "").lower())


def _patient_name_tokens(value: str | None) -> list[str]:
    return re.findall(r"[a-z0-9]+", (value or "").lower())


def _same_patient_identity(left: str | None, right: str | None) -> bool:
    """Match expanded/corrected fax names without guessing across patients."""
    left_tokens = _patient_name_tokens(left)
    right_tokens = _patient_name_tokens(right)
    return len(left_tokens) >= 2 and left_tokens[:2] == right_tokens[:2]


def _existing_case_for_row(
    row: FaxIngestRow,
    *,
    exact: dict[tuple[date, str], list[SurgicalCase]],
    by_date: dict[date, list[SurgicalCase]],
) -> SurgicalCase | None:
    matches = exact.get((row.case_date, _normal(row.patient_name)), [])
    if matches:
        return matches[0]
    if row.start_time is None:
        return None
    identity_matches = [
        case
        for case in by_date.get(row.case_date, [])
        if case.start_time == row.start_time
        and _same_patient_identity(case.patient_name, row.patient_name)
    ]
    return identity_matches[0] if len(identity_matches) == 1 else None


def _surgeon_initials(surgeon: Surgeon) -> str:
    return f"{(surgeon.first_name or '')[:1]}{(surgeon.last_name or '')[:1]}".upper()


def _is_hospital(location: Location) -> bool:
    return (
        (location.location_type or "").lower() in {"hospital", "or"}
        or (location.abbreviation or "").upper().endswith("-OR")
    )


def _fax_note(notes: str | None, fax_id: int) -> str:
    marker = f"Fax {fax_id} daily snapshot. No surgeon notification sent."
    current = (notes or "").strip()
    if marker.lower() in current.lower():
        return current
    return f"{current}\n{marker}".strip()


def _applicable_row_ids(db: Session, run_id: int) -> set[int]:
    return {
        row_id
        for (row_id,) in db.execute(
            text("SELECT fax_row_id FROM fax_ingest_rows_applicable WHERE run_id = :run_id"),
            {"run_id": run_id},
        )
    }


def _scope_surgeons(db: Session, run: FaxIngestRun) -> dict[str, Surgeon]:
    try:
        scope = {str(value).strip().upper() for value in json.loads(run.surgeon_scope_json or "[]")}
    except (TypeError, ValueError):
        scope = set()
    surgeons = db.query(Surgeon).filter(Surgeon.is_active == True).all()  # noqa: E712
    by_initials: dict[str, list[Surgeon]] = defaultdict(list)
    for surgeon in surgeons:
        by_initials[_surgeon_initials(surgeon)].append(surgeon)
    resolved: dict[str, Surgeon] = {}
    for initials in scope:
        matches = by_initials.get(initials, [])
        if len(matches) != 1:
            raise ValueError(f"Fax surgeon scope is not unique in CAL: {initials}")
        resolved[initials] = matches[0]
    return resolved


def _card_location(card: ScheduleCard, rows: list[FaxIngestRow]) -> int | None:
    """Choose a display anchor without discarding row-level facilities.

    A permanent AM/PM card may contain sequential activity at more than one
    facility. Prefer the immutable master location when it appears in the fax;
    otherwise use the first scheduled row. Individual activities retain their
    own source_location_id.
    """
    explicit_ids = {row.source_location_id for row in rows if row.source_location_id}
    if card.baseline_location_id in explicit_ids:
        return card.baseline_location_id
    if card.effective_location_id in explicit_ids:
        return card.effective_location_id
    explicit_rows = [row for row in rows if row.source_location_id]
    if explicit_rows:
        first = min(explicit_rows, key=lambda row: (row.start_time is None, row.start_time, row.id))
        return first.source_location_id
    return card.effective_location_id or card.baseline_location_id


def _case_group_key(row: FaxIngestRow) -> tuple[date, str, str, str]:
    clock = row.start_time.strftime("%H:%M") if row.start_time else ""
    return row.case_date, clock, (row.room_text or "").upper(), _normal(row.patient_name)


def _choose_primary(
    rows: list[FaxIngestRow],
    *,
    existing: SurgicalCase | None,
    cards: dict[tuple[int, date, str], ScheduleCard],
    location_id: int,
) -> tuple[int, int | None]:
    surgeon_ids = list(dict.fromkeys(row.surgeon_id for row in rows if row.surgeon_id))
    if not surgeon_ids:
        raise ValueError("Surgical fax row has no surgeon.")
    if len(surgeon_ids) > 2:
        raise ValueError("A fax case matched more than two surgeons.")
    if existing and existing.surgeon_id in surgeon_ids:
        primary = existing.surgeon_id
    elif len(surgeon_ids) == 1:
        primary = surgeon_ids[0]
    else:
        baseline_matches = []
        for row in rows:
            if not row.surgeon_id:
                continue
            card = cards[(row.surgeon_id, row.case_date, row.session)]
            if card.baseline_state == "assigned" and card.baseline_location_id == location_id:
                baseline_matches.append(row.surgeon_id)
        baseline_matches = list(dict.fromkeys(baseline_matches))
        if len(baseline_matches) != 1:
            raise ValueError(
                f"Shared case on {rows[0].case_date.isoformat()} at "
                f"{rows[0].start_time} has no unique primary surgeon."
            )
        primary = baseline_matches[0]
    assistant = next((value for value in surgeon_ids if value != primary), None)
    return primary, assistant


def apply_staged_snapshot(
    db: Session,
    *,
    source_fax_id: int,
    run_id: int,
    admin_id: int | None = None,
) -> dict[str, Any]:
    """Backup then reconcile one staged fax without creating schedule cards."""
    run = db.get(FaxIngestRun, run_id)
    if not run:
        raise ValueError("Fax ingest run not found.")
    document = db.get(FaxDocument, run.fax_document_id)
    if not document or document.external_fax_id != source_fax_id:
        raise ValueError("Fax ingest run does not belong to this fax.")
    if document.status == "applied":
        raise ValueError("This fax was already applied.")
    newer_applied = db.query(FaxDocument.id).filter(
        FaxDocument.external_fax_id > source_fax_id,
        FaxDocument.status == "applied",
    ).first()
    if newer_applied:
        raise ValueError("A newer fax was already applied; older snapshots cannot replace it.")
    if run.status == "applied":
        raise ValueError("This fax ingest run was already applied.")
    all_rows = db.query(FaxIngestRow).filter(FaxIngestRow.run_id == run.id).all()
    if not all_rows:
        raise ValueError("Fax ingest run has no rows.")
    applicable_ids = _applicable_row_ids(db, run.id)
    rows = [row for row in all_rows if row.id in applicable_ids]
    skipped_rows = len(all_rows) - len(rows)
    if not rows:
        raise ValueError("Fax ingest run has no applicable rows.")
    validate_page_ownership(db, document, rows)
    start = min(row.case_date for row in rows)
    end = max(row.case_date for row in rows)
    if (end - start).days > 7:
        raise ValueError("Fax snapshot spans more than eight calendar days.")

    scope = _scope_surgeons(db, run)
    if not scope:
        raise ValueError("Fax ingest run has no surgeon scope.")
    scope_ids = {surgeon.id for surgeon in scope.values()}
    row_surgeon_ids = {row.surgeon_id for row in rows if row.surgeon_id}
    if not row_surgeon_ids.issubset(scope_ids):
        raise ValueError("Fax rows include a surgeon outside the reviewed fax scope.")

    cards_list = db.query(ScheduleCard).filter(
        ScheduleCard.surgeon_id.in_(scope_ids),
        ScheduleCard.date >= start,
        ScheduleCard.date <= end,
    ).all()
    cards = {(card.surgeon_id, card.date, card.session): card for card in cards_list}

    activity: dict[tuple[int, date, str], list[FaxIngestRow]] = defaultdict(list)
    for row in rows:
        activity[(row.surgeon_id, row.case_date, row.session)].append(row)
    effective_locations: dict[tuple[int, date, str], int | None] = {}
    mixed_location_ids: dict[tuple[int, date, str], list[int]] = {}
    for key, group in activity.items():
        card = cards[key]
        explicit = {row.source_location_id for row in group if row.source_location_id}
        location_id = _card_location(card, group)
        effective_locations[key] = location_id
        if len(explicit) > 1:
            mixed_location_ids[key] = sorted(explicit)

    backup = create_fax_snapshot_backup(
        db,
        admin_id=admin_id,
        start=start,
        end=end,
        fax_id=source_fax_id,
    )
    # The backup commits, which clears transaction-local settings.
    mark_fax_ingest_transaction(db, run.id)

    conflicts: list[dict[str, Any]] = []
    for key, location_id in effective_locations.items():
        card = cards[key]
        if card.effective_state == "off":
            conflicts.append({
                "code": "off_collision",
                "surgeonId": card.surgeon_id,
                "date": card.date.isoformat(),
                "session": card.session,
                "faxLocationId": location_id,
            })
            continue
        if card.baseline_state == "assigned" and card.baseline_location_id != location_id:
            conflicts.append({
                "code": "baseline_changed_by_epic",
                "surgeonId": card.surgeon_id,
                "date": card.date.isoformat(),
                "session": card.session,
                "baselineLocationId": card.baseline_location_id,
                "faxLocationId": location_id,
            })
        if key in mixed_location_ids:
            conflicts.append({
                "code": "mixed_facilities_in_session",
                "surgeonId": card.surgeon_id,
                "date": card.date.isoformat(),
                "session": card.session,
                "cardLocationId": location_id,
                "faxLocationIds": mixed_location_ids[key],
            })

    clinic_sessions = len({
        (row.surgeon_id, row.case_date, row.session) for row in rows if row.row_type == "clinic"
    })

    surgical_groups: dict[tuple[date, str, str, str], list[FaxIngestRow]] = defaultdict(list)
    for row in rows:
        if row.row_type == "surgical":
            surgical_groups[_case_group_key(row)].append(row)
    existing_cases = db.query(SurgicalCase).filter(
        SurgicalCase.date >= start,
        SurgicalCase.date <= end,
        SurgicalCase.status != "cancelled",
    ).all()
    existing_by_patient: dict[tuple[date, str], list[SurgicalCase]] = defaultdict(list)
    existing_by_date: dict[date, list[SurgicalCase]] = defaultdict(list)
    for case in existing_cases:
        existing_by_patient[(case.date, _normal(case.patient_name))].append(case)
        existing_by_date[case.date].append(case)

    kept_case_ids: set[int] = set()
    created = updated = assisted = 0
    for group in surgical_groups.values():
        first = group[0]
        existing = _existing_case_for_row(
            first,
            exact=existing_by_patient,
            by_date=existing_by_date,
        )
        location_id = first.source_location_id or effective_locations[(first.surgeon_id, first.case_date, first.session)]
        primary_id, assistant_id = _choose_primary(
            group,
            existing=existing,
            cards=cards,
            location_id=location_id,
        )
        if existing:
            case = existing
            updated += 1
        else:
            case = SurgicalCase(
                surgeon_id=primary_id,
                date=first.case_date,
                patient_name=first.patient_name,
                procedure=first.procedure or "TBD",
            )
            db.add(case)
            db.flush()
            created += 1
        case.surgeon_id = primary_id
        case.assisting_surgeon_id = assistant_id
        case.patient_name = first.patient_name
        case.start_time = first.start_time
        case.location_id = location_id
        case.schedule_card_id = cards[(primary_id, first.case_date, first.session)].id
        case.room_text = (first.room_text or "").upper()
        case.procedure = max((row.procedure or "" for row in group), key=len, default="") or case.procedure or "TBD"
        case.status = "scheduled"
        case.or_block_instance_id = None
        case.notes = _fax_note(case.notes, source_fax_id)
        from .schedule_activity_normalization import normalize_surgical_case_card
        normalize_surgical_case_card(db, case)
        kept_case_ids.add(case.id)
        if assistant_id:
            assisted += 1

    cancelled = kept_by_database = 0
    for case in existing_cases:
        if case.id in kept_case_ids or case.surgeon_id not in scope_ids:
            continue
        if not FAX_NOTE_RE.search(case.notes or ""):
            continue
        case.status = "cancelled"
        case.notes = _fax_note(case.notes, source_fax_id)
        db.flush()
        db.refresh(case)
        if case.status == "cancelled":
            cancelled += 1
        else:
            kept_by_database += 1
        from .schedule_activity_normalization import normalize_surgical_case_card
        normalize_surgical_case_card(db, case)

    run.status = "applied"
    document.status = "applied"
    from .schedule_activity_normalization import sync_applied_fax_clinic_activities
    sync_applied_fax_clinic_activities(db, run)
    db.add(ScheduleChangeEvent(
        event_type="fax_daily_snapshot_applied",
        surgeon_id=None,
        title=f"Fax {source_fax_id} daily schedule snapshot",
        body=(
            f"Applied fax {source_fax_id} line items; block cards unchanged. "
            f"cases created={created}, updated={updated}, cancelled={cancelled}, "
            f"kept on unapplied days={kept_by_database}; rows skipped={skipped_rows}; "
            f"clinic sessions={clinic_sessions}; conflicts={len(conflicts)}. "
            "No surgeon notification sent."
        ),
        payload=json.dumps({
            "faxId": source_fax_id,
            "runId": run.id,
            "backupId": backup.id,
            "range": {"start": start.isoformat(), "end": end.isoformat()},
            "conflicts": conflicts,
        }),
    ))
    db.commit()
    cleanup = {"files": 0, "bytes": 0}
    cleanup_errors: list[str] = []
    superseded_documents = db.query(FaxDocument).filter(
        FaxDocument.external_fax_id <= source_fax_id,
    ).all()
    for fax_document in superseded_documents:
        try:
            removed = cleanup_fax_derivatives(fax_document)
            cleanup["files"] += removed["files"]
            cleanup["bytes"] += removed["bytes"]
        except OSError as exc:
            message = f"fax {fax_document.external_fax_id} derivative cleanup: {exc}"
            cleanup_errors.append(message)
            logger.warning(message)
    source_cleanup = {"files": 0, "bytes": 0}
    try:
        source_cleanup = prune_immutable_fax_sources(db, keep=3)
    except OSError as exc:
        message = f"immutable source cleanup: {exc}"
        cleanup_errors.append(message)
        logger.warning(message)
    return {
        "ok": True,
        "faxId": source_fax_id,
        "runId": run.id,
        "backupId": backup.id,
        "range": {"start": start.isoformat(), "end": end.isoformat()},
        "rows": len(rows),
        "surgicalCreated": created,
        "surgicalUpdated": updated,
        "surgicalCancelled": cancelled,
        "surgicalKeptOnUnappliedDays": kept_by_database,
        "rowsSkipped": skipped_rows,
        "assistedCases": assisted,
        "clinicSessions": clinic_sessions,
        "baselineConflicts": conflicts,
        "cardsCreated": 0,
        "cardsChanged": 0,
        "notificationsSent": 0,
        "derivativesRemoved": cleanup,
        "immutableSourcesRemoved": source_cleanup,
        "cleanupErrors": cleanup_errors,
    }
