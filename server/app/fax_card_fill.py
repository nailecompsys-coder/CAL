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
_RETIRE, _FILL, _ALREADY, _ACTIVE = _STATEMENTS


def fill_cards_from_fax_lines(db: Session, *, run_id: int) -> dict[str, int]:
    """One SQL fill. The applicable-row view decides which lines land on which cards."""
    params = {"run_id": run_id}
    already = int(db.execute(text(_ALREADY), params).scalar() or 0)
    retired = db.execute(text(_RETIRE), params).all()
    db.execute(text(_FILL), params)
    active = int(db.execute(text(_ACTIVE), params).scalar() or 0)
    return {
        "surgicalCreated": active - already,
        "surgicalUpdated": already,
        "surgicalCancelled": sum(1 for row in retired if row[0] == "surgical"),
        "surgicalKeptOnUnappliedDays": 0,
    }
