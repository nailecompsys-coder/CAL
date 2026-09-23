"""Materialize the permanent AM/PM cards from the Master Schedule only."""

from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy.orm import Session

from .admin_schedule_template_clinic_service import week_pattern_matches
from .models import ScheduleCard, ScheduleCardWeek, Surgeon, SurgeonLocationSchedule
from .surgeon_visibility import surgeon_is_visible


CARD_STATES = {"assigned", "na", "off"}


def monday_for(day: date) -> date:
    return day - timedelta(days=day.weekday())


def _master_cell(
    templates: dict[tuple[int, int, str], SurgeonLocationSchedule],
    surgeon_id: int,
    day: date,
    session: str,
) -> SurgeonLocationSchedule | None:
    cell = templates.get((surgeon_id, day.weekday(), session))
    return cell if cell and week_pattern_matches(day, cell.week_pattern) else None


def _card_values(cell: SurgeonLocationSchedule | None) -> dict:
    if cell is None:
        return {
            "baseline_state": "na",
            "effective_state": "na",
            "baseline_location_id": None,
            "effective_location_id": None,
            "master_template_id": None,
            "master_week_pattern": "all",
        }
    state = (cell.assignment_type or "na").strip().lower()
    if state in {"blank", "float"}:
        state = "na"
    if state not in CARD_STATES:
        raise ValueError(f"Unsupported master-card state: {state}")
    return {
        "baseline_state": state,
        "effective_state": state,
        "baseline_location_id": cell.location_id,
        "effective_location_id": cell.location_id,
        "master_template_id": cell.id,
        "master_week_pattern": cell.week_pattern or "all",
    }


def materialize_master_schedule_cards(
    db: Session,
    *,
    start: date,
    end: date,
    surgeon_ids: list[int] | None = None,
    master_revision: str = "master-v1",
) -> dict:
    """Create the permanent 10-card weeks. Existing card identity is preserved."""
    if end < start:
        raise ValueError("end must be on or after start")
    surgeons_query = db.query(Surgeon).filter(
        Surgeon.is_active == True,  # noqa: E712
        Surgeon.staff_type == "physician",
    )
    if surgeon_ids is not None:
        surgeons_query = surgeons_query.filter(Surgeon.id.in_(surgeon_ids))
    surgeons = [row for row in surgeons_query.order_by(Surgeon.id).all() if surgeon_is_visible(row)]
    ids = [row.id for row in surgeons]
    templates = {
        (row.surgeon_id, row.day_of_week, (row.session or "").lower()): row
        for row in db.query(SurgeonLocationSchedule).filter(SurgeonLocationSchedule.surgeon_id.in_(ids)).all()
    } if ids else {}

    current_monday = monday_for(start)
    final_monday = monday_for(end)
    weeks_created = 0
    cards_created = 0
    cards_preserved = 0
    while current_monday <= final_monday:
        for surgeon in surgeons:
            week = db.query(ScheduleCardWeek).filter(
                ScheduleCardWeek.surgeon_id == surgeon.id,
                ScheduleCardWeek.week_start == current_monday,
            ).one_or_none()
            if week is None:
                week = ScheduleCardWeek(
                    surgeon_id=surgeon.id,
                    week_start=current_monday,
                    master_revision=master_revision,
                )
                db.add(week)
                db.flush()
                weeks_created += 1
            for offset in range(5):
                day = current_monday + timedelta(days=offset)
                for session in ("am", "pm"):
                    existing = db.query(ScheduleCard).filter(
                        ScheduleCard.surgeon_id == surgeon.id,
                        ScheduleCard.date == day,
                        ScheduleCard.session == session,
                    ).one_or_none()
                    if existing is not None:
                        cards_preserved += 1
                        continue
                    db.add(ScheduleCard(
                        week_id=week.id,
                        surgeon_id=surgeon.id,
                        date=day,
                        session=session,
                        source="master",
                        **_card_values(_master_cell(templates, surgeon.id, day, session)),
                    ))
                    cards_created += 1
        current_monday += timedelta(days=7)
    db.flush()
    from .day_off_card_normalization import sync_day_off_links_for_range
    sync_day_off_links_for_range(db, start, end)
    return {
        "weeksCreated": weeks_created,
        "cardsCreated": cards_created,
        "cardsPreserved": cards_preserved,
        "surgeons": len(surgeons),
    }


def apply_master_schedule_to_cards(
    db: Session,
    *,
    start: date,
    end: date,
    surgeon_ids: list[int] | None = None,
    master_revision: str = "master-v1",
) -> dict:
    """Apply master rules to existing cards; this function never creates cards.

    This is intentionally strict. A missing AM/PM scaffold card is an integrity
    failure because allowing a fallback creation would reintroduce extra cards.
    """
    if end < start:
        raise ValueError("end must be on or after start")
    surgeons_query = db.query(Surgeon).filter(
        Surgeon.is_active == True,  # noqa: E712
        Surgeon.staff_type == "physician",
    )
    if surgeon_ids is not None:
        surgeons_query = surgeons_query.filter(Surgeon.id.in_(surgeon_ids))
    surgeons = [row for row in surgeons_query.order_by(Surgeon.id).all() if surgeon_is_visible(row)]
    ids = [row.id for row in surgeons]
    templates = {
        (row.surgeon_id, row.day_of_week, (row.session or "").lower()): row
        for row in db.query(SurgeonLocationSchedule).filter(SurgeonLocationSchedule.surgeon_id.in_(ids)).all()
    } if ids else {}
    cards = db.query(ScheduleCard).filter(
        ScheduleCard.surgeon_id.in_(ids),
        ScheduleCard.date >= start,
        ScheduleCard.date <= end,
    ).all() if ids else []
    by_key = {(row.surgeon_id, row.date, row.session): row for row in cards}

    expected: list[tuple[int, date, str]] = []
    day = start
    while day <= end:
        if day.weekday() < 5:
            expected.extend((surgeon.id, day, session) for surgeon in surgeons for session in ("am", "pm"))
        day += timedelta(days=1)
    missing = [key for key in expected if key not in by_key]
    if missing:
        sample = ", ".join(f"surgeon={sid} {day.isoformat()} {session}" for sid, day, session in missing[:5])
        raise ValueError(f"Missing permanent schedule card(s): {sample}")

    changed = 0
    state_counts = {state: 0 for state in CARD_STATES}
    for surgeon_id, day, session in expected:
        card = by_key[(surgeon_id, day, session)]
        values = _card_values(_master_cell(templates, surgeon_id, day, session))
        state_counts[values["baseline_state"]] += 1
        fields = (
            "baseline_state",
            "effective_state",
            "baseline_location_id",
            "effective_location_id",
            "master_template_id",
            "master_week_pattern",
        )
        if any(getattr(card, field) != values[field] for field in fields):
            for field in fields:
                setattr(card, field, values[field])
            card.source = "master"
            card.version += 1
            changed += 1
        card.week.master_revision = master_revision
    db.flush()
    return {
        "cardsApplied": len(expected),
        "cardsChanged": changed,
        "assigned": state_counts["assigned"],
        "na": state_counts["na"],
        "off": state_counts["off"],
        "missing": 0,
    }
