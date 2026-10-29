"""Apply one reviewed daily fax as the authoritative rolling schedule snapshot."""

from __future__ import annotations

import json
import logging
from datetime import date
from typing import Any

from sqlalchemy import func, text
from sqlalchemy.orm import Session

from .models import (
    FaxDocument,
    FaxIngestRow,
    FaxIngestRun,
    FaxRowDecision,
    ScheduleCard,
    ScheduleCardActivity,
    ScheduleChangeEvent,
)
from .fax_card_fill import fill_cards_from_fax_lines
from .fax_conflict_notices import notify_off_day_conflicts
from .fax_ingest_engine import mark_fax_ingest_transaction, run_report
from .fax_restore_service import replace_fax_warnings, save_fax_line_photo
from .fax_pdf_intake import cleanup_fax_derivatives, prune_immutable_fax_sources
from .schedule_build_backup_service import create_fax_snapshot_backup

logger = logging.getLogger(__name__)


def discard_applied_scratch_rows(db: Session, run_id: int) -> int:
    """The card line remembers the fax. This send's scratch reading can go."""
    rows = db.query(FaxIngestRow).filter(FaxIngestRow.run_id == run_id).all()
    if not rows:
        return 0
    row_ids = [row.id for row in rows]
    db.query(ScheduleCardActivity).filter(
        ScheduleCardActivity.fax_ingest_row_id.in_(row_ids)
    ).update({ScheduleCardActivity.fax_ingest_row_id: None}, synchronize_session=False)
    db.query(FaxRowDecision).filter(
        FaxRowDecision.fax_row_id.in_(row_ids)
    ).delete(synchronize_session=False)
    db.query(FaxIngestRow).filter(FaxIngestRow.id.in_(row_ids)).delete(synchronize_session=False)
    for row in rows:
        db.expunge(row)
    return len(row_ids)


def _applicable_row_ids(db: Session, run_id: int) -> set[int]:
    return {
        row_id
        for (row_id,) in db.execute(
            text("SELECT fax_row_id FROM fax_ingest_rows_applicable WHERE run_id = :run_id"),
            {"run_id": run_id},
        )
    }


def apply_staged_snapshot(
    db: Session,
    *,
    source_fax_id: int,
    run_id: int,
    admin_id: int | None = None,
) -> dict[str, Any]:
    """Backup, then one SQL fill places every staged detail line on its existing card."""
    run = db.get(FaxIngestRun, run_id)
    if not run:
        raise ValueError("Fax ingest run not found.")
    document = db.get(FaxDocument, run.fax_document_id)
    if not document or document.external_fax_id != source_fax_id:
        raise ValueError("Fax ingest run does not belong to this fax.")
    newer_applied = db.execute(text("""
        SELECT newer_document.id
        FROM fax_documents newer_document
        JOIN fax_ingest_runs newer_run ON newer_run.fax_document_id = newer_document.id
        JOIN fax_documents current_document ON current_document.id = :document_id
        WHERE newer_document.id <> current_document.id
          AND (
                COALESCE(newer_document.source_received_at, newer_document.created_at),
                newer_document.external_fax_id
              ) > (
                COALESCE(current_document.source_received_at, current_document.created_at),
                current_document.external_fax_id
              )
          AND newer_document.status = 'applied'
          AND (
              NOT EXISTS (SELECT 1 FROM fax_ingest_coverage newer_any WHERE newer_any.run_id = newer_run.id)
              OR EXISTS (
                  SELECT 1
                  FROM fax_ingest_coverage current_coverage
                  JOIN fax_ingest_coverage newer_coverage
                    ON newer_coverage.run_id = newer_run.id
                   AND newer_coverage.surgeon_id = current_coverage.surgeon_id
                   AND newer_coverage.case_date = current_coverage.case_date
                  WHERE current_coverage.run_id = :run_id
              )
          )
        LIMIT 1
    """), {"document_id": document.id, "run_id": run.id}).first()
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
    bounds = db.execute(text("""
        SELECT min(case_date) AS start_date, max(case_date) AS end_date
        FROM fax_ingest_coverage WHERE run_id = :run_id
    """), {"run_id": run.id}).one()
    start, end = bounds.start_date, bounds.end_date
    if start is None or end is None:
        raise ValueError("Fax ingest run has no SQL coverage.")
    if isinstance(start, str):
        start = date.fromisoformat(start)
    if isinstance(end, str):
        end = date.fromisoformat(end)
    # Don's rule 4: no day-span limit. Epic faxes can run a month or more out.

    scope_ids = {
        surgeon_id for (surgeon_id,) in db.execute(
            text("SELECT DISTINCT surgeon_id FROM fax_ingest_coverage WHERE run_id = :run_id ORDER BY surgeon_id"),
            {"run_id": run.id},
        )
    }
    if not scope_ids:
        raise ValueError("Fax ingest run has no surgeon scope.")
    row_surgeon_ids = {row.surgeon_id for row in rows if row.surgeon_id}
    if not row_surgeon_ids.issubset(scope_ids):
        raise ValueError("Fax rows include a surgeon outside the reviewed fax scope.")

    cards_list = db.query(ScheduleCard).filter(
        ScheduleCard.surgeon_id.in_(scope_ids),
        ScheduleCard.date >= start,
        ScheduleCard.date <= end,
    ).all()
    cards = {(card.surgeon_id, card.date, card.session): card for card in cards_list}

    backup = create_fax_snapshot_backup(
        db,
        admin_id=admin_id,
        start=start,
        end=end,
        fax_id=source_fax_id,
    )
    # The backup commits, which clears transaction-local settings.
    mark_fax_ingest_transaction(db, run.id)

    conflicts = [dict(row) for row in db.execute(text("""
        SELECT CASE WHEN decision.reason_code = 'epic_override'
                    THEN 'baseline_changed_by_epic'
                    ELSE decision.reason_code END AS code,
               fax_row.surgeon_id AS "surgeonId",
               fax_row.case_date AS date,
               fax_row.session,
               card.baseline_location_id AS "baselineLocationId",
               fax_row.source_location_id AS "faxLocationId"
        FROM fax_ingest_rows fax_row
        JOIN fax_row_decisions decision ON decision.fax_row_id = fax_row.id
        JOIN schedule_cards card ON card.id = decision.schedule_card_id
        WHERE fax_row.run_id = :run_id
          AND decision.status = 'ready_with_warning'
        ORDER BY fax_row.surgeon_id, fax_row.case_date, fax_row.session, fax_row.id
    """), {"run_id": run.id}).mappings()]
    for conflict in conflicts:
        conflict["date"] = conflict["date"].isoformat() if hasattr(conflict["date"], "isoformat") else str(conflict["date"])
    mixed = db.execute(text("""
        SELECT fax_row.surgeon_id AS "surgeonId", fax_row.case_date AS date, fax_row.session
        FROM fax_ingest_rows_applicable applicable
        JOIN fax_ingest_rows fax_row ON fax_row.id = applicable.fax_row_id
        WHERE applicable.run_id = :run_id AND fax_row.source_location_id IS NOT NULL
        GROUP BY fax_row.surgeon_id, fax_row.case_date, fax_row.session
        HAVING count(DISTINCT fax_row.source_location_id) > 1
        ORDER BY fax_row.surgeon_id, fax_row.case_date, fax_row.session
    """), {"run_id": run.id}).mappings()
    for row in mixed:
        conflict = dict(row)
        conflict["code"] = "mixed_facilities_in_session"
        conflict["date"] = conflict["date"].isoformat() if hasattr(conflict["date"], "isoformat") else str(conflict["date"])
        conflicts.append(conflict)

    photo = save_fax_line_photo(
        db,
        source_fax_id=source_fax_id,
        run_id=run.id,
        covered={
            (surgeon_id, case_date)
            for surgeon_id, case_date in db.execute(text("""
                SELECT surgeon_id, case_date
                FROM fax_ingest_coverage
                WHERE run_id = :run_id
                ORDER BY surgeon_id, case_date
            """), {"run_id": run.id})
        },
    )
    warning_count = replace_fax_warnings(
        db,
        source_fax_id=source_fax_id,
        conflicts=conflicts,
        cards=cards,
    )

    clinic_sessions = int(db.execute(text("""
        SELECT count(*) FROM (
            SELECT DISTINCT fax_row.surgeon_id, fax_row.case_date, fax_row.session
            FROM fax_ingest_rows_applicable applicable
            JOIN fax_ingest_rows fax_row ON fax_row.id = applicable.fax_row_id
            WHERE applicable.run_id = :run_id AND fax_row.row_type = 'clinic'
        ) clinic_groups
    """), {"run_id": run.id}).scalar() or 0)

    # Rule 10: compute OFF-day conflicts before the scratch rows are discarded.
    off_conflicts = notify_off_day_conflicts(db, run_id=run.id, source_fax_id=source_fax_id)
    report = run_report(db, run.id, lines_added=len(rows))
    filled = fill_cards_from_fax_lines(db, run_id=run.id)
    created = filled["surgicalCreated"]
    updated = filled["surgicalUpdated"]
    cancelled = filled["surgicalCancelled"]
    kept_by_database = filled["surgicalKeptOnUnappliedDays"]

    run.status = "applied"
    document.status = "applied"
    discard_applied_scratch_rows(db, run.id)
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
            "restoreSetId": photo.id,
            "warningCount": warning_count,
            "range": {"start": start.isoformat(), "end": end.isoformat()},
            "conflicts": conflicts,
            "report": {**report, "conflictsFlagged": sum(c["lines"] for c in off_conflicts)},
        }),
    ))
    db.commit()
    cleanup = {"files": 0, "bytes": 0}
    cleanup_errors: list[str] = []
    current_order = document.source_received_at or document.created_at
    superseded_documents = db.query(FaxDocument).filter(
        func.coalesce(FaxDocument.source_received_at, FaxDocument.created_at) <= current_order,
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
        "restoreSetId": photo.id,
        "warningCount": warning_count,
        "range": {"start": start.isoformat(), "end": end.isoformat()},
        "rows": len(rows),
        "surgicalCreated": created,
        "surgicalUpdated": updated,
        "surgicalCancelled": cancelled,
        "surgicalKeptOnUnappliedDays": kept_by_database,
        "rowsSkipped": skipped_rows,
        "assistedCases": 0,
        "clinicSessions": clinic_sessions,
        "baselineConflicts": conflicts,
        "cardsCreated": 0,
        "cardsChanged": 0,
        "notificationsSent": 0,
        "adminConflictNotices": len(off_conflicts),
        "offDayConflicts": off_conflicts,
        "linesDeactivated": 0,
        "report": {**report, "conflictsFlagged": sum(c["lines"] for c in off_conflicts)},
        "derivativesRemoved": cleanup,
        "immutableSourcesRemoved": source_cleanup,
        "cleanupErrors": cleanup_errors,
    }
