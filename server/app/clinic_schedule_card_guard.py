from __future__ import annotations

from datetime import date

from sqlalchemy.orm import Session

from .models import ClinicSchedule


CARD_SESSIONS = ("am", "pm")


def normalize_card_session(session: str | None) -> str:
    raw = (session or "am").strip().lower()
    return raw if raw in CARD_SESSIONS else "am"


def target_card_sessions(session: str | None) -> list[str]:
    raw = (session or "am").strip().lower()
    if raw == "full":
        return ["am", "pm"]
    return [normalize_card_session(raw)]


def normalize_clinic_day_cards(db: Session, surgeon_id: int, day: date) -> int:
    """Hard invariant: max one AM card and one PM card per surgeon/day.

    Any legacy `full` rows are converted into AM/PM cards. Duplicate AM or PM
    rows are removed. This is intentionally small and boring because every
    writer calls it before commit.
    """
    rows = (
        db.query(ClinicSchedule)
        .filter(ClinicSchedule.surgeon_id == surgeon_id, ClinicSchedule.date == day)
        .order_by(ClinicSchedule.id)
        .all()
    )
    if not rows:
        return 0

    changed = 0
    kept_rows: list[ClinicSchedule] = []
    for row in rows:
        if (row.assignment_type or "assigned").lower() == "off":
            db.delete(row)
            changed += 1
            continue
        kept_rows.append(row)
    rows = kept_rows
    if not rows:
        return changed

    full_rows = [row for row in rows if (row.session or "").lower() == "full"]
    deleted_full_ids: set[int] = set()
    for row in full_rows:
        has_am = any((other.session or "").lower() == "am" for other in rows if other.id != row.id)
        has_pm = any((other.session or "").lower() == "pm" for other in rows if other.id != row.id)
        if has_am:
            db.delete(row)
            if row.id:
                deleted_full_ids.add(row.id)
            changed += 1
        else:
            row.session = "am"
            changed += 1
        if not has_pm:
            clone = ClinicSchedule(
                surgeon_id=row.surgeon_id,
                location_id=row.location_id,
                date=row.date,
                session="pm",
                assignment_type=row.assignment_type or "assigned",
                notes=row.notes,
            )
            db.add(clone)
            db.flush()
            rows.append(clone)
            changed += 1

    keep_by_session: dict[str, ClinicSchedule] = {}
    for row in sorted((item for item in rows if item.id not in deleted_full_ids), key=lambda item: item.id or 0):
        session = normalize_card_session(row.session)
        row.session = session
        if session not in keep_by_session:
            keep_by_session[session] = row
            continue
        kept = keep_by_session[session]
        if not (kept.notes or "").strip() and (row.notes or "").strip():
            kept.notes = row.notes
        db.delete(row)
        changed += 1
    return changed


def upsert_clinic_schedule_cards(
    db: Session,
    *,
    surgeon_id: int,
    day: date,
    session: str,
    location_id: int | None,
    assignment_type: str,
    notes: str | None = None,
    replace_day: bool = False,
) -> int:
    """Create/update schedule cards without ever exceeding AM + PM."""
    sessions = target_card_sessions(session)
    query = db.query(ClinicSchedule).filter(
        ClinicSchedule.surgeon_id == surgeon_id,
        ClinicSchedule.date == day,
    )
    existing = query.all()
    existing_by_session = {
        normalize_card_session(row.session): row
        for row in existing
        if (row.session or "").lower() != "full"
    }
    touched = 0

    for row in existing:
        row_session = (row.session or "").lower()
        should_remove = row_session == "full" or (replace_day and normalize_card_session(row_session) not in sessions)
        if should_remove:
            db.delete(row)
            touched += 1
            existing_by_session.pop(normalize_card_session(row_session), None)

    db.flush()
    for card_session in sessions:
        row = existing_by_session.get(card_session)
        if row is None:
            row = ClinicSchedule(
                surgeon_id=surgeon_id,
                location_id=location_id,
                date=day,
                session=card_session,
                assignment_type=assignment_type,
                notes=notes,
            )
            db.add(row)
            db.flush()
            touched += 1
            continue
        row.location_id = location_id
        row.assignment_type = assignment_type
        row.notes = notes
        touched += 1

    touched += normalize_clinic_day_cards(db, surgeon_id, day)
    return touched
