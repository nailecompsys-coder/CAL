"""Don's rule 10 (amended by his big rule, Oct 29, 2026).

A patient on an OFF card or an approved day off is a conflict. The line is
still entered (Epic is the source) and the card gets an in-CAL flag
(schedule_warnings, see fax_snapshot_service). Fax ingest NEVER sends a
notification: no AdminNotification, SMS, email or push. This module only reads.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date

from sqlalchemy import text
from sqlalchemy.orm import Session

from .fax_ingest_guardrails import approved_day_off_for_ingest


def _as_date(value) -> date:
    return value if isinstance(value, date) else date.fromisoformat(str(value)[:10])


def off_day_conflicts(db: Session, run_id: int) -> list[dict]:
    """Applicable rows that land on an OFF card or an approved day off, grouped by surgeon/day."""
    rows = db.execute(text("""
        SELECT fax_row.surgeon_id, fax_row.case_date, fax_row.session, fax_row.start_time,
               decision.reason_code
        FROM fax_ingest_rows_applicable applicable
        JOIN fax_ingest_rows fax_row ON fax_row.id = applicable.fax_row_id
        JOIN fax_row_decisions decision ON decision.fax_row_id = fax_row.id
        WHERE applicable.run_id = :run_id
        ORDER BY fax_row.surgeon_id, fax_row.case_date, fax_row.session, fax_row.id
    """), {"run_id": run_id}).all()
    grouped: dict[tuple[int, date], dict] = defaultdict(lambda: {"lines": 0, "sessions": set(), "dayOffId": None})
    for surgeon_id, case_date, session, start_time, reason in rows:
        day = _as_date(case_date)
        day_off = None
        if reason != "off_collision":
            day_off = approved_day_off_for_ingest(db, surgeon_id=surgeon_id, day=day, session=session)
            if day_off is None:
                continue
        item = grouped[(surgeon_id, day)]
        item["lines"] += 1
        item["sessions"].add(session)
        if day_off is not None:
            item["dayOffId"] = day_off.id
    return [
        {"surgeonId": sid, "date": day.isoformat(), "lines": v["lines"],
         "sessions": sorted(v["sessions"]), "dayOffId": v["dayOffId"]}
        for (sid, day), v in sorted(grouped.items())
    ]
