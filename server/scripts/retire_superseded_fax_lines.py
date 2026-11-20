"""One-time cleanup: only the latest fax is the source of truth (Don, Nov 20).

For every doctor and every future date, keep only the fax lines from the newest
applied fax that included that doctor and covers that date. Older fax lines are
switched off (is_active = FALSE), never deleted. Manual and Aprima lines are not
touched. A doctor/day where the governing fax has a row CAL could not place is
left alone. Counts only are printed; no patient details.

Dry run by default. Run inside the cal_api container:
    python scripts/retire_superseded_fax_lines.py            # dry run
    python scripts/retire_superseded_fax_lines.py --apply    # switch lines off
"""

from __future__ import annotations

import json
import sys

from sqlalchemy import text

from app.database import SessionLocal
from app.models import ScheduleChangeEvent

SUPERSEDED = """
WITH fax AS (
    SELECT d.external_fax_id AS fax_id, r.id AS run_id,
           COALESCE(d.source_received_at, d.created_at) AS received,
           (SELECT min(case_date) FROM fax_ingest_coverage cv WHERE cv.run_id = r.id) AS s,
           (SELECT max(case_date) FROM fax_ingest_coverage cv WHERE cv.run_id = r.id) AS e
    FROM fax_documents d JOIN fax_ingest_runs r ON r.fax_document_id = d.id
    WHERE d.status = 'applied' AND r.status = 'applied'
),
line AS (
    SELECT a.id, a.surgeon_id, a.activity_date, a.source_fax_id
    FROM schedule_card_activities a
    WHERE a.source_system = 'fax' AND a.is_active = TRUE
      AND a.activity_date > (now() AT TIME ZONE 'America/New_York')::date
),
governing AS (
    SELECT l.id, l.surgeon_id, l.activity_date, l.source_fax_id, (
        SELECT f.fax_id FROM fax f
        WHERE l.activity_date BETWEEN f.s AND f.e
          AND EXISTS (SELECT 1 FROM fax_ingest_coverage cv WHERE cv.run_id = f.run_id AND cv.surgeon_id = l.surgeon_id)
        ORDER BY f.received DESC, f.fax_id DESC LIMIT 1
    ) AS gov_fax
    FROM line l
)
SELECT g.id, g.surgeon_id, g.activity_date, g.gov_fax
FROM governing g
WHERE g.gov_fax IS NOT NULL AND g.source_fax_id <> g.gov_fax
  AND NOT EXISTS (
      SELECT 1 FROM fax_ingest_candidate_resolutions h
      JOIN fax_ingest_runs r ON r.id = h.run_id JOIN fax_documents d ON d.id = r.fax_document_id
      WHERE d.external_fax_id = g.gov_fax AND h.decision_status = 'unresolved'
        AND h.surgeon_id = g.surgeon_id AND h.case_date = g.activity_date)
"""


def main(apply: bool) -> int:
    db = SessionLocal()
    try:
        rows = db.execute(text(SUPERSEDED)).mappings().all()
        ids = [row["id"] for row in rows]
        per_day: dict[str, int] = {}
        for row in rows:
            key = f"surgeon {row['surgeon_id']} {row['activity_date']} (latest fax {row['gov_fax']})"
            per_day[key] = per_day.get(key, 0) + 1
        for key in sorted(per_day):
            print(f"{key}: {per_day[key]} line(s)")
        print(f"total: {len(ids)} line(s) {'switched off' if apply else 'would be switched off (dry run)'}")
        if apply and ids:
            db.execute(
                text("UPDATE schedule_card_activities SET is_active = FALSE WHERE id = ANY(:ids)"),
                {"ids": ids},
            )
            db.add(ScheduleChangeEvent(
                event_type="fax_superseded_lines_retired",
                surgeon_id=None,
                title="Old fax lines switched off: latest fax is the source of truth",
                body=f"{len(ids)} fax line(s) no longer on the latest fax for their doctor/date were switched off.",
                payload=json.dumps({"activityIds": ids}),
            ))
            db.commit()
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main(apply="--apply" in sys.argv[1:]))
