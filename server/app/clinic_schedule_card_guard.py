"""The morning card and the afternoon card are the clinic place.

Writers update those cards. They do not create a second list.
"""

from __future__ import annotations

from datetime import date

from sqlalchemy.orm import Session, joinedload

from .models import ScheduleCard


CARD_SESSIONS = ("am", "pm")


def normalize_card_session(session: str | None) -> str:
    raw = (session or "am").strip().lower()
    return raw if raw in CARD_SESSIONS else "am"


def target_card_sessions(session: str | None) -> list[str]:
    raw = (session or "am").strip().lower()
    if raw == "full":
        return ["am", "pm"]
    return [normalize_card_session(raw)]


def present_card(card: ScheduleCard) -> ScheduleCard:
    """Give a card the place fields older readers already understand."""
    card.location = card.effective_location
    card.location_id = card.effective_location_id
    card.assignment_type = card.effective_state
    card.notes = ""
    return card


def place_cards(db: Session, *criteria) -> list[ScheduleCard]:
    query = (
        db.query(ScheduleCard)
        .options(
            joinedload(ScheduleCard.effective_location),
            joinedload(ScheduleCard.surgeon),
        )
    )
    for criterion in criteria:
        query = query.filter(criterion)
    return [present_card(card) for card in query.all()]


def set_card_place(card: ScheduleCard, location_id: int | None, assignment_type: str | None) -> None:
    kind = (assignment_type or "assigned").lower()
    if kind == "off":
        card.baseline_state = "off"
        card.effective_state = "off"
        card.baseline_location_id = None
        card.effective_location_id = None
        return
    if kind in {"na", "float"} or not location_id:
        card.baseline_state = "na"
        card.effective_state = "na"
        card.baseline_location_id = None
        card.effective_location_id = None
        return
    card.baseline_state = "assigned"
    card.effective_state = "assigned"
    card.baseline_location_id = location_id
    card.effective_location_id = location_id


def normalize_clinic_day_cards(db: Session, surgeon_id: int, day: date) -> int:
    """Cards are already one morning and one afternoon. Nothing to split."""
    del db, surgeon_id, day
    return 0


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
    """Update the existing morning and afternoon cards. A missing card is left alone."""
    del notes
    sessions = target_card_sessions(session)
    touched = 0
    if replace_day:
        extras = db.query(ScheduleCard).filter(
            ScheduleCard.surgeon_id == surgeon_id,
            ScheduleCard.date == day,
            ScheduleCard.session.notin_(sessions),
        ).all()
        for card in extras:
            set_card_place(card, None, "na")
            touched += 1
    for card_session in sessions:
        card = db.query(ScheduleCard).filter_by(
            surgeon_id=surgeon_id,
            date=day,
            session=card_session,
        ).one_or_none()
        if card is None:
            continue
        set_card_place(card, location_id, assignment_type)
        touched += 1
    return touched
