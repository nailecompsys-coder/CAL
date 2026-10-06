"""Read-only comparison of a reviewed fax with the live schedule.

The rows are staged and decided exactly as a real ingest would, labelled in
SQL against live activities, then the whole transaction is rolled back.
"""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.orm import Session

from .fax_ingest_engine import ReviewedFaxRow, stage_reviewed_rows

SAME_ITEM = """
    a.is_active
    AND a.surgeon_id = r.surgeon_id
    AND a.activity_date = r.case_date
    AND a.activity_type = r.row_type
    AND lower(trim(a.patient_name)) = lower(trim(r.patient_name))
    AND (a.start_time = r.start_time OR (a.start_time IS NULL AND r.start_time IS NULL))
"""

FAX_ROWS_SQL = f"""
SELECT r.page_number AS page, r.surgeon_initials, r.case_date, r.start_time, r.session,
       r.row_type, r.room_text, r.patient_name, r.procedure,
       d.reason_code, d.detail,
       c.effective_state AS card_state, cl.abbreviation AS card_location,
       fl.abbreviation AS fax_location,
       CASE
           WHEN d.status <> 'ready' THEN 'fail'
           WHEN d.reason_code = 'epic_override'
                AND r.source_location_id IS DISTINCT FROM COALESCE(c.effective_location_id, c.baseline_location_id) THEN 'fail'
           WHEN EXISTS (SELECT 1 FROM schedule_card_activities a WHERE {SAME_ITEM}) THEN 'match'
           ELSE 'addition'
       END AS label
FROM fax_ingest_rows r
JOIN fax_row_decisions d ON d.fax_row_id = r.id
LEFT JOIN schedule_cards c ON c.id = d.schedule_card_id
LEFT JOIN locations cl ON cl.id = COALESCE(c.effective_location_id, c.baseline_location_id)
LEFT JOIN locations fl ON fl.id = r.source_location_id
WHERE r.run_id = :run_id
ORDER BY r.surgeon_initials, r.case_date, r.start_time, r.id
"""

CAL_ONLY_SQL = f"""
SELECT upper(substr(s.first_name, 1, 1) || substr(s.last_name, 1, 1)) AS surgeon_initials,
       a.activity_date AS case_date, a.start_time, a.session, a.activity_type AS row_type,
       a.patient_name, a.procedure, l.abbreviation AS location, a.source_system
FROM schedule_card_activities a
JOIN surgeons s ON s.id = a.surgeon_id
LEFT JOIN locations l ON l.id = a.location_id
WHERE a.is_active
  AND a.source_system IN ('surgical_case', 'fax_clinic')
  AND EXISTS (
      SELECT 1 FROM fax_ingest_rows r
      WHERE r.run_id = :run_id AND r.surgeon_id = a.surgeon_id AND r.case_date = a.activity_date
  )
  AND NOT EXISTS (SELECT 1 FROM fax_ingest_rows r WHERE r.run_id = :run_id AND {SAME_ITEM})
ORDER BY surgeon_initials, a.activity_date, a.start_time, a.id
"""


def _plain(row) -> dict:
    return {key: (value.isoformat() if hasattr(value, "isoformat") else value) for key, value in row.items()}


def preview_reviewed_rows(db: Session, *, external_fax_id: int, source_label: str, rows: list[ReviewedFaxRow]) -> dict:
    try:
        staged = stage_reviewed_rows(db, external_fax_id=external_fax_id, source_label=source_label, rows=rows)
        params = {"run_id": staged["runId"]}
        fax_rows = [_plain(row) for row in db.execute(text(FAX_ROWS_SQL), params).mappings()]
        cal_only = [_plain(row) for row in db.execute(text(CAL_ONLY_SQL), params).mappings()]
    finally:
        db.rollback()
    return {"rows": fax_rows, "calOnly": cal_only}
