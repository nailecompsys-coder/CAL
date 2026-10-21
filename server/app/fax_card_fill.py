"""Fill existing AM/PM cards from fax lines the database has already accepted."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import text
from sqlalchemy.orm import Session

_STATEMENTS = [
    part.strip()
    for part in Path(__file__).with_name("sql").joinpath("fill_cards_from_fax.sql").read_text().split("\n-- @@\n")
    if part.strip()
]
_CLEAR_ABSENCES, _RECORD_ABSENCES, _RETIRE, _FILL, _ALREADY, _ACTIVE = _STATEMENTS


def fill_cards_from_fax_lines(db: Session, *, run_id: int) -> dict[str, int]:
    """One SQL fill. The applicable-row view decides which lines land on which cards."""
    params = {"run_id": run_id}
    already = int(db.execute(text(_ALREADY), params).scalar() or 0)
    db.execute(text(_CLEAR_ABSENCES), params)
    db.execute(text(_RECORD_ABSENCES), params)
    retired = db.execute(text(_RETIRE), params).all()
    db.execute(text(_FILL), params)
    active = int(db.execute(text(_ACTIVE), params).scalar() or 0)
    return {
        "surgicalCreated": active - already,
        "surgicalUpdated": already,
        "surgicalCancelled": sum(1 for row in retired if row[0] == "surgical"),
        "surgicalKeptOnUnappliedDays": int(db.execute(text("""
            SELECT count(*)
            FROM fax_line_absences absence
            JOIN schedule_card_activities activity ON activity.id = absence.schedule_card_activity_id
            WHERE absence.run_id = :run_id
              AND activity.is_active = TRUE
              AND activity.activity_type = 'surgical'
        """), params).scalar() or 0),
    }
