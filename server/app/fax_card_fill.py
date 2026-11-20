"""Fill existing AM/PM cards from fax lines the database has already accepted."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.orm import Session

_STATEMENTS = [
    part.strip()
    for part in Path(__file__).with_name("sql").joinpath("fill_cards_from_fax.sql").read_text().split("\n-- @@\n")
    if part.strip()
]
_NEWER_FAX_WINS, _FILL, _ALREADY, _ACTIVE = _STATEMENTS


def fill_cards_from_fax_lines(db: Session, *, run_id: int) -> dict[str, int]:
    """One SQL fill. The applicable-row view decides which lines land on which cards.

    Don's rules: ingest only adds/updates line items on existing cards (rule 1)
    and the newer fax wins for a day (rule 5). Lines the latest fax no longer
    lists are switched off afterwards (retire_lines_not_on_latest_fax).
    """
    params = {"run_id": run_id}
    db.execute(text(_NEWER_FAX_WINS), params)
    already = int(db.execute(text(_ALREADY), params).scalar() or 0)
    db.execute(text(_FILL), params)
    active = int(db.execute(text(_ACTIVE), params).scalar() or 0)
    return {
        "surgicalCreated": active - already,
        "surgicalUpdated": already,
        "surgicalCancelled": 0,
        "surgicalKeptOnUnappliedDays": 0,
        "linesDeactivated": 0,
    }


# Don (Nov 20): only the latest fax is the source of truth. Epic faxes come in
# batches of doctors, so it is per doctor: for each doctor ON this fax, for every
# date the fax covers (tomorrow on), a fax line this fax did not write is
# switched off (Epic took it away). Doctors not on this fax are not touched. Lines from Shannon/admin or Aprima are never
# touched, nor lines from a fax newer than this one. A doctor/day where this fax
# has a row CAL could not place keeps its lines until that row is fixed.
_LATEST_FAX_FILTER = """
FROM schedule_card_activities a
WHERE a.source_system = 'fax'
  AND a.is_active = TRUE
  AND a.activity_date >= :start
  AND a.activity_date <= :end
  AND a.activity_date > :today
  AND a.surgeon_id IN (SELECT cv.surgeon_id FROM fax_ingest_coverage cv WHERE cv.run_id = :run_id)
  AND a.source_record_key NOT IN (
      SELECT CAST(doc.external_fax_id AS TEXT) || '|' || fax_row.normalized_key
      FROM fax_ingest_rows_applicable applicable
      JOIN fax_ingest_rows fax_row ON fax_row.id = applicable.fax_row_id
      JOIN fax_ingest_runs run ON run.id = fax_row.run_id
      JOIN fax_documents doc ON doc.id = run.fax_document_id
      WHERE applicable.run_id = :run_id
  )
  AND NOT EXISTS (
      SELECT 1 FROM fax_ingest_candidate_resolutions held
      WHERE held.run_id = :run_id
        AND held.decision_status = 'unresolved'
        AND held.surgeon_id = a.surgeon_id
        AND held.case_date = a.activity_date
  )
  AND NOT EXISTS (
      SELECT 1
      FROM fax_documents line_doc, fax_documents this_doc
      WHERE line_doc.external_fax_id = a.source_fax_id
        AND this_doc.external_fax_id = :fax_id
        AND (COALESCE(line_doc.source_received_at, line_doc.created_at), line_doc.external_fax_id)
          > (COALESCE(this_doc.source_received_at, this_doc.created_at), this_doc.external_fax_id)
  )
"""

_LATEST_FAX_SCOPE = "SELECT DISTINCT a.surgeon_id, a.activity_date " + _LATEST_FAX_FILTER
_LATEST_FAX_RETIRE = (
    "UPDATE schedule_card_activities SET is_active = FALSE WHERE id IN (SELECT a.id "
    + _LATEST_FAX_FILTER + ")"
)


def _params(run_id, fax_id, start, end, today):
    return {"run_id": run_id, "fax_id": fax_id, "start": start, "end": end, "today": today}


def lines_not_on_latest_fax(db: Session, *, run_id: int, fax_id: int, start, end, today) -> set[tuple]:
    """(surgeon_id, date) pairs holding fax lines this fax will switch off (for the undo photo)."""
    rows = db.execute(text(_LATEST_FAX_SCOPE), _params(run_id, fax_id, start, end, today)).all()
    return {(int(sid), day if not isinstance(day, str) else date.fromisoformat(day[:10])) for sid, day in rows}


def retire_lines_not_on_latest_fax(db: Session, *, run_id: int, fax_id: int, start, end, today) -> int:
    """Switch off fax lines the latest fax no longer lists. Returns how many."""
    result = db.execute(text(_LATEST_FAX_RETIRE), _params(run_id, fax_id, start, end, today))
    return int(result.rowcount or 0)
