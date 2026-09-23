"""Apply one reviewed daily fax as the authoritative rolling schedule snapshot."""

from __future__ import annotations

import json
import re
from collections import defaultdict
from datetime import date
from typing import Any

from sqlalchemy.orm import Session

from .models import (
    ClinicSchedule,
    FaxDocument,
    FaxIngestRow,
    FaxIngestRun,
    Location,
    ScheduleCard,
    ScheduleChangeEvent,
    Surgeon,
    SurgicalCase,
)
from .fax_pdf_intake import cleanup_fax_derivatives, prune_immutable_fax_sources
from .schedule_build_backup_service import create_fax_snapshot_backup


FAX_NOTE_RE = re.compile(r"\bFax\s+\d+\b", re.IGNORECASE)


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


def _card_location(card: ScheduleCard, explicit_ids: set[int]) -> int | None:
    if len(explicit_ids) > 1:
        raise ValueError(
            f"Fax has multiple locations for surgeon {card.surgeon_id} on "
            f"{card.date.isoformat()} {card.session.upper()}."
        )
    if explicit_ids:
        return next(iter(explicit_ids))
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
    if run.status == "applied":
        raise ValueError("This fax ingest run was already applied.")
    rows = db.query(FaxIngestRow).filter(FaxIngestRow.run_id == run.id).all()
    if not rows:
        raise ValueError("Fax ingest run has no rows.")
    if any(row.surgeon_id is None for row in rows):
        raise ValueError("Fax ingest has unresolved surgeons.")
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
    missing = [
        row for row in rows
        if (row.surgeon_id, row.case_date, row.session) not in cards
    ]
    if missing:
        row = missing[0]
        raise ValueError(
            f"Permanent card missing for {row.surgeon_initials} "
            f"{row.case_date.isoformat()} {row.session.upper()}."
        )

    activity: dict[tuple[int, date, str], list[FaxIngestRow]] = defaultdict(list)
    for row in rows:
        activity[(row.surgeon_id, row.case_date, row.session)].append(row)
    effective_locations: dict[tuple[int, date, str], int] = {}
    for key, group in activity.items():
        card = cards[key]
        explicit = {row.source_location_id for row in group if row.source_location_id}
        location_id = _card_location(card, explicit)
        if not location_id:
            raise ValueError(
                f"Fax location is unresolved for {group[0].surgeon_initials} "
                f"{card.date.isoformat()} {card.session.upper()}."
            )
        effective_locations[key] = location_id

    backup = create_fax_snapshot_backup(
        db,
        admin_id=admin_id,
        start=start,
        end=end,
        fax_id=source_fax_id,
    )

    conflicts: list[dict[str, Any]] = []
    for card in cards_list:
        if (card.source or "").startswith("fax:") and card.effective_state != "off":
            card.effective_state = card.baseline_state
            card.effective_location_id = card.baseline_location_id
            card.source = "master"
            card.version = (card.version or 0) + 1

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
        if card.baseline_state != "assigned" or card.baseline_location_id != location_id:
            conflicts.append({
                "code": "baseline_changed_by_epic",
                "surgeonId": card.surgeon_id,
                "date": card.date.isoformat(),
                "session": card.session,
                "baselineLocationId": card.baseline_location_id,
                "faxLocationId": location_id,
            })
        card.effective_state = "assigned"
        card.effective_location_id = location_id
        card.source = f"fax:{source_fax_id}"
        card.version = (card.version or 0) + 1

    prior_clinic = db.query(ClinicSchedule).filter(
        ClinicSchedule.surgeon_id.in_(scope_ids),
        ClinicSchedule.date >= start,
        ClinicSchedule.date <= end,
    ).all()
    for schedule in prior_clinic:
        if not FAX_NOTE_RE.search(schedule.notes or ""):
            continue
        card = cards.get((schedule.surgeon_id, schedule.date, schedule.session))
        schedule.notes = None
        if card:
            schedule.location_id = card.baseline_location_id
            if schedule.assignment_type != "off":
                schedule.assignment_type = "assigned"

    clinic_groups: dict[tuple[int, date, str], list[FaxIngestRow]] = defaultdict(list)
    for row in rows:
        if row.row_type == "clinic":
            clinic_groups[(row.surgeon_id, row.case_date, row.session)].append(row)
    clinic_updated = 0
    for key, group in clinic_groups.items():
        surgeon_id, day, session = key
        schedule = db.query(ClinicSchedule).filter_by(
            surgeon_id=surgeon_id,
            date=day,
            session=session,
        ).one_or_none()
        if not schedule:
            schedule = ClinicSchedule(surgeon_id=surgeon_id, date=day, session=session)
            db.add(schedule)
        if schedule.assignment_type != "off":
            schedule.assignment_type = "assigned"
            schedule.location_id = effective_locations[key]
        visits = "; ".join(
            f"{row.start_time.strftime('%H:%M')} {row.patient_name}"
            for row in sorted(group, key=lambda value: (value.start_time, value.patient_name))
            if row.start_time
        )
        schedule.notes = f"Fax {source_fax_id} visual SOT · {visits}"
        clinic_updated += 1

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
        location_id = effective_locations[(first.surgeon_id, first.case_date, first.session)]
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

    cancelled = 0
    for case in existing_cases:
        if case.id in kept_case_ids or case.surgeon_id not in scope_ids:
            continue
        if not FAX_NOTE_RE.search(case.notes or ""):
            continue
        case.status = "cancelled"
        case.notes = _fax_note(case.notes, source_fax_id)
        from .schedule_activity_normalization import normalize_surgical_case_card
        normalize_surgical_case_card(db, case)
        cancelled += 1

    run.status = "applied"
    document.status = "applied"
    from .schedule_activity_normalization import sync_applied_fax_clinic_activities
    sync_applied_fax_clinic_activities(db, run)
    db.add(ScheduleChangeEvent(
        event_type="fax_daily_snapshot_applied",
        surgeon_id=None,
        title=f"Fax {source_fax_id} daily schedule snapshot",
        body=(
            f"Applied fax {source_fax_id} to existing cards only. "
            f"cases created={created}, updated={updated}, cancelled={cancelled}; "
            f"clinic sessions={clinic_updated}; conflicts={len(conflicts)}. "
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
    superseded_documents = db.query(FaxDocument).filter(
        FaxDocument.external_fax_id <= source_fax_id,
    ).all()
    for fax_document in superseded_documents:
        removed = cleanup_fax_derivatives(fax_document)
        cleanup["files"] += removed["files"]
        cleanup["bytes"] += removed["bytes"]
    source_cleanup = prune_immutable_fax_sources(db, keep=3)
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
        "assistedCases": assisted,
        "clinicSessionsUpdated": clinic_updated,
        "baselineConflicts": conflicts,
        "cardsCreated": 0,
        "notificationsSent": 0,
        "derivativesRemoved": cleanup,
        "immutableSourcesRemoved": source_cleanup,
    }
