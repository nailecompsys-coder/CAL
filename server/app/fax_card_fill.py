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
_NEWER_FAX_WINS, _FILL, _ALREADY, _ACTIVE = _STATEMENTS


def fill_cards_from_fax_lines(db: Session, *, run_id: int) -> dict[str, int]:
    """One SQL fill. The applicable-row view decides which lines land on which cards.

    Don's rules: ingest only adds/updates line items on existing cards (rule 1),
    never deactivates a line (rule 2), and the newer fax wins for a day (rule 5).
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
