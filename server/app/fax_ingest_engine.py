"""SQL-owned staging for structured fax extractor handback rows.

The extractor reads pixels. This module records its immutable handback, then
asks SQL to resolve surgeon, session, location, card, and decision facts.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date, datetime, time
from zoneinfo import ZoneInfo

from sqlalchemy import text
from sqlalchemy.orm import Session

from .models import FaxDocument, FaxIngestCandidate, FaxIngestRun

ENGINE_VERSION = "fax-sql-stage-v3"
PRACTICE_TZ = ZoneInfo("America/New_York")


@dataclass(frozen=True)
class ReviewedFaxRow:
    page: int
    surgeon_initials: str
    surgeon_name: str | None
    case_date: date | str
    start_time: time | str | None
    row_type: str
    room: str
    patient_name: str
    procedure: str = ""
    extraction_flags: str | None = None
    source_row_number: int | None = None


def practice_today() -> date:
    return datetime.now(PRACTICE_TZ).date()


def _row_day(value: date | str) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(_text(value)[:10])
    except ValueError:
        return None


def split_future_rows(rows: list[ReviewedFaxRow], today: date | None = None) -> tuple[list[ReviewedFaxRow], int]:
    """Don's rule 3: rows dated today or earlier are skipped entirely.

    They are not staged and do not count toward coverage or absences. Rows with
    an unreadable date are kept so SQL can hold them as invalid_date.
    """
    cutoff = today or practice_today()
    kept: list[ReviewedFaxRow] = []
    skipped = 0
    for row in rows:
        day = _row_day(row.case_date)
        if day is not None and day <= cutoff:
            skipped += 1
            continue
        kept.append(row)
    return kept, skipped


def _name_key(value: str | None) -> str:
    raw = _text(value).lower()
    raw = re.sub(r"\[[^\]]*\]", " ", raw)
    raw = re.sub(r"\b(md|do|facs|pa-c|np)\b", " ", raw)
    if "," in raw:
        last, _, first = raw.partition(",")
        raw = f"{first} {last}"
    return " ".join(sorted(re.findall(r"[a-z]+", raw)))


def surgeon_is_patient_name(row: ReviewedFaxRow, patient_keys: set[str]) -> bool:
    """Don's rule 6: a patient name is never a surgeon."""
    key = _name_key(row.surgeon_name)
    return bool(key) and key in patient_keys


def mark_fax_ingest_transaction(db: Session, run_id: int | None = None) -> None:
    if db.bind.dialect.name != "postgresql":
        return
    db.execute(
        text("SELECT set_config('cal.writer', 'fax_ingest', true), set_config('cal.fax_run_id', :run_id, true)"),
        {"run_id": str(run_id or "")},
    )


def _text(value: str | None) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def _raw_date(value: date | str) -> str:
    return value.isoformat() if isinstance(value, date) else _text(value)


def _raw_time(value: time | str | None) -> str | None:
    if isinstance(value, time):
        return value.isoformat()
    return _text(value) or None


_MATERIALIZE_ROWS = """
INSERT INTO fax_ingest_rows (
    run_id, candidate_id, page_number, source_row_number, surgeon_id,
    surgeon_initials, case_date, start_time, session, row_type, room_text,
    patient_name, procedure, source_location_id, normalized_key, extraction_flags
)
SELECT
    run_id, id, page_number, source_row_number, surgeon_id,
    wanted_initials, case_date, start_time, COALESCE(resolved_session, 'pm'),
    COALESCE(card_row_type, lower(trim(row_type_raw))), upper(trim(COALESCE(room_raw, ''))),
    trim(COALESCE(patient_name_raw, '')), trim(COALESCE(procedure_raw, '')),
    source_location_id,
    CAST(page_number AS TEXT) || '|' || CAST(source_row_number AS TEXT),
    extraction_flags
FROM fax_ingest_candidate_resolutions
WHERE run_id = :run_id
  AND case_date IS NOT NULL
  AND lower(trim(row_type_raw)) IN ('surgical', 'clinic')
ORDER BY page_number, source_row_number
"""

_MATERIALIZE_DECISIONS = """
INSERT INTO fax_row_decisions (fax_row_id, schedule_card_id, status, reason_code, detail)
SELECT row.id, resolution.schedule_card_id,
       resolution.decision_status, resolution.reason_code,
       CASE resolution.reason_code
         WHEN 'off_collision' THEN 'Patient on an OFF day: line entered and Shannon/Don notified.'
         WHEN 'location_conflict' THEN 'Room code, block and card location disagree; held for review.'
         WHEN 'past_time' THEN 'Dated today or earlier; fax ingest never touches it.'
         WHEN 'weekend_schedule' THEN 'Epic OR/clinic work is not accepted on a weekend.'
         WHEN 'unknown_surgeon' THEN 'No unique active surgeon matched the extractor handback.'
         WHEN 'missing_time' THEN 'The extractor handback has no usable start time.'
         WHEN 'missing_scaffold' THEN 'The permanent AM/PM card is missing; ingest cannot create one.'
         WHEN 'block_facility_unclear' THEN 'More than one assigned block fits this time.'
         WHEN 'no_block_for_facility' THEN 'Placeholder/unknown room and no block or card location establishes the facility.'
         WHEN 'extraction_flagged' THEN 'The extractor flagged this source row for review.'
         ELSE 'SQL resolved this row to the existing permanent card.'
       END
FROM fax_ingest_rows row
JOIN fax_ingest_candidate_resolutions resolution ON resolution.id = row.candidate_id
WHERE row.run_id = :run_id
ORDER BY row.page_number, row.source_row_number
"""

_DERIVE_COVERAGE = """
INSERT INTO fax_ingest_coverage (run_id, surgeon_id, case_date)
SELECT DISTINCT :run_id, resolution.surgeon_id, resolution.case_date
FROM fax_ingest_candidate_resolutions resolution
WHERE resolution.run_id = :run_id
  AND resolution.surgeon_id IS NOT NULL
  AND resolution.case_date IS NOT NULL
  AND resolution.decision_status IN ('ready', 'ready_with_warning')
ON CONFLICT (run_id, surgeon_id, case_date) DO NOTHING
"""


def stage_reviewed_rows(
    db: Session,
    *,
    external_fax_id: int,
    source_label: str,
    rows: list[ReviewedFaxRow],
    surgeon_scope: list[str] | None = None,
    extractor_name: str = "structured_extract",
    extractor_version: str | None = None,
    extractor_request_id: str | None = None,
    source_received_at: datetime | None = None,
    coverage: list[tuple[str, date]] | None = None,
) -> dict:
    """Record extractor candidates and materialize SQL-owned decisions."""
    if not rows:
        raise ValueError("rows required")
    if db.bind.dialect.name == "sqlite":
        # Production creates the views during startup migration. Isolated SQLite
        # tests create metadata directly, so install the same SQL views here.
        from .migrate_fax_ingest import create_applicable_view
        create_applicable_view(db.connection())
    mark_fax_ingest_transaction(db)
    document = db.query(FaxDocument).filter(FaxDocument.external_fax_id == external_fax_id).one_or_none()
    if document is None:
        document = FaxDocument(
            external_fax_id=external_fax_id,
            source_label=_text(source_label) or "Structured fax extraction",
            source_received_at=source_received_at,
        )
        db.add(document)
        db.flush()
    elif source_received_at is not None:
        document.source_received_at = source_received_at
    scope = sorted({value.strip().upper() for value in (surgeon_scope or []) if value.strip()})
    if not scope:
        scope = sorted({_text(row.surgeon_initials).upper() for row in rows if _text(row.surgeon_initials)})
    run = FaxIngestRun(
        fax_document_id=document.id,
        engine_version=ENGINE_VERSION,
        status="staged",
        surgeon_scope_json=json.dumps(scope),
        extractor_name=_text(extractor_name) or "structured_extract",
        extractor_version=_text(extractor_version) or None,
        extractor_request_id=_text(extractor_request_id) or None,
    )
    db.add(run)
    db.flush()

    # CAL owns candidate row numbers. Extractors may send a mix of explicit and
    # missing (or duplicate) row numbers on one page; trusting them let an
    # auto-assigned number collide with an explicit one and fail the whole fax
    # with a unique violation. Number rows 1..n per page in arrival order and
    # keep the extractor's original number in evidence_ref for traceability.
    page_row_numbers: dict[int, int] = {}
    patient_keys = {_name_key(row.patient_name) for row in rows if _name_key(row.patient_name)}
    for row in rows:
        surgeon_initials = _text(row.surgeon_initials).upper()
        extraction_flags = _text(row.extraction_flags) or None
        if surgeon_is_patient_name(row, patient_keys):
            # Held as unknown_surgeon; never matched by initials.
            surgeon_initials = ""
        source_row_number = page_row_numbers.get(row.page, 0) + 1
        page_row_numbers[row.page] = source_row_number
        desk_row = row.source_row_number if row.source_row_number is not None else "none"
        db.add(FaxIngestCandidate(
            run_id=run.id,
            page_number=row.page,
            source_row_number=source_row_number,
            surgeon_initials_raw=surgeon_initials,
            surgeon_name_raw=_text(row.surgeon_name) or None,
            case_date_raw=_raw_date(row.case_date),
            start_time_raw=_raw_time(row.start_time),
            row_type_raw=_text(row.row_type).lower(),
            room_raw=_text(row.room),
            patient_name_raw=_text(row.patient_name),
            procedure_raw=_text(row.procedure),
            extraction_flags=extraction_flags,
            evidence_ref=f"page:{row.page}:row:{source_row_number}:desk_row:{desk_row}",
        ))
    db.flush()
    db.execute(text(_MATERIALIZE_ROWS), {"run_id": run.id})
    db.execute(text(_MATERIALIZE_DECISIONS), {"run_id": run.id})
    # SQL owns authoritative coverage. A Desk/OCR header may contain a validly
    # formatted but wrong date, so only dates with at least one SQL-resolved row
    # may govern the live snapshot. Unresolved dates remain staged for review.
    db.execute(text(_DERIVE_COVERAGE), {"run_id": run.id})
    counts = {
        status: count
        for status, count in db.execute(text("""
            SELECT resolution.decision_status, count(*)
            FROM fax_ingest_candidate_resolutions resolution
            WHERE resolution.run_id = :run_id
            GROUP BY resolution.decision_status
            ORDER BY resolution.decision_status
        """), {"run_id": run.id})
    }
    materialized = int(db.execute(
        text("SELECT count(*) FROM fax_ingest_rows WHERE run_id = :run_id"),
        {"run_id": run.id},
    ).scalar() or 0)
    return {
        "faxDocumentId": document.id,
        "runId": run.id,
        "rows": len(rows),
        "materializedRows": materialized,
        "decisions": counts,
        "report": run_report(db, run.id),
        "writeMode": "staging_only",
    }


def run_report(db: Session, run_id: int, *, lines_added: int | None = None) -> dict:
    """Don's rule 12: added / held by reason / conflicts flagged / deactivated (always 0)."""
    held = {
        reason: int(count)
        for reason, count in db.execute(text("""
            SELECT resolution.reason_code, count(*)
            FROM fax_ingest_candidate_resolutions resolution
            WHERE resolution.run_id = :run_id AND resolution.decision_status = 'unresolved'
            GROUP BY resolution.reason_code ORDER BY resolution.reason_code
        """), {"run_id": run_id})
    }
    conflicts = int(db.execute(text("""
        SELECT count(*) FROM fax_ingest_candidate_resolutions resolution
        WHERE resolution.run_id = :run_id AND resolution.reason_code = 'off_collision'
    """), {"run_id": run_id}).scalar() or 0)
    ready = int(db.execute(text("""
        SELECT count(*) FROM fax_ingest_candidate_resolutions resolution
        WHERE resolution.run_id = :run_id AND resolution.decision_status IN ('ready', 'ready_with_warning')
    """), {"run_id": run_id}).scalar() or 0)
    return {
        "linesAdded": ready if lines_added is None else lines_added,
        "linesHeld": sum(held.values()),
        "heldByReason": held,
        "conflictsFlagged": conflicts,
        "linesDeactivated": 0,
    }
