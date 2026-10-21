"""SQL-owned staging for structured fax extractor handback rows.

The extractor reads pixels. This module records its immutable handback, then
asks SQL to resolve surgeon, session, location, card, and decision facts.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date, time

from sqlalchemy import text
from sqlalchemy.orm import Session

from .models import FaxDocument, FaxIngestCandidate, FaxIngestRun

ENGINE_VERSION = "fax-sql-stage-v2"


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
    lower(trim(row_type_raw)), upper(trim(COALESCE(room_raw, ''))),
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
         WHEN 'off_collision' THEN 'Verified fax work overlaps OFF; preserve both and show a warning.'
         WHEN 'epic_override' THEN 'Verified source location differs from the fixed master location; preserve both.'
         WHEN 'weekend_schedule' THEN 'Epic OR/clinic work is not accepted on a weekend.'
         WHEN 'unknown_surgeon' THEN 'No unique active surgeon matched the extractor handback.'
         WHEN 'missing_time' THEN 'The extractor handback has no usable start time.'
         WHEN 'missing_scaffold' THEN 'The permanent AM/PM card is missing; ingest cannot create one.'
         WHEN 'block_facility_unclear' THEN 'More than one assigned block fits this time.'
         WHEN 'no_block_for_facility' THEN 'No assigned block or fixed card location establishes the facility.'
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
        document = FaxDocument(external_fax_id=external_fax_id, source_label=_text(source_label) or "Structured fax extraction")
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
        extractor_name=_text(extractor_name) or "structured_extract",
        extractor_version=_text(extractor_version) or None,
        extractor_request_id=_text(extractor_request_id) or None,
    )
    db.add(run)
    db.flush()

    page_row_numbers: dict[int, int] = {}
    for row in rows:
        source_row_number = row.source_row_number or (page_row_numbers.get(row.page, 0) + 1)
        if source_row_number < 1:
            raise ValueError("source_row_number must be positive")
        page_row_numbers[row.page] = source_row_number
        db.add(FaxIngestCandidate(
            run_id=run.id,
            page_number=row.page,
            source_row_number=source_row_number,
            surgeon_initials_raw=_text(row.surgeon_initials).upper(),
            surgeon_name_raw=_text(row.surgeon_name) or None,
            case_date_raw=_raw_date(row.case_date),
            start_time_raw=_raw_time(row.start_time),
            row_type_raw=_text(row.row_type).lower(),
            room_raw=_text(row.room),
            patient_name_raw=_text(row.patient_name),
            procedure_raw=_text(row.procedure),
            extraction_flags=_text(row.extraction_flags) or None,
            evidence_ref=f"page:{row.page}:row:{source_row_number}",
        ))
    db.flush()
    db.execute(text(_MATERIALIZE_ROWS), {"run_id": run.id})
    db.execute(text(_MATERIALIZE_DECISIONS), {"run_id": run.id})
    if coverage:
        expected_coverage = {(_text(initials).upper(), covered_day) for initials, covered_day in coverage}
        for initials, covered_day in coverage:
            db.execute(text("""
                INSERT INTO fax_ingest_coverage (run_id, surgeon_id, case_date)
                SELECT :run_id, min(surgeon.id), :case_date
                FROM surgeons surgeon
                WHERE surgeon.is_active = TRUE
                  AND upper(substr(COALESCE(surgeon.first_name, ''), 1, 1) ||
                            substr(COALESCE(surgeon.last_name, ''), 1, 1)) = :initials
                HAVING count(surgeon.id) = 1
                ON CONFLICT (run_id, surgeon_id, case_date) DO NOTHING
            """), {
                "run_id": run.id,
                "case_date": covered_day,
                "initials": _text(initials).upper(),
            })
        saved_coverage = int(db.execute(
            text("SELECT count(*) FROM fax_ingest_coverage WHERE run_id = :run_id"),
            {"run_id": run.id},
        ).scalar() or 0)
        if saved_coverage != len(expected_coverage):
            raise ValueError("Fax coverage contains an unknown or ambiguous surgeon.")
    else:
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
        "writeMode": "staging_only",
    }
