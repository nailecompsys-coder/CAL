from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy.orm import Session

from .conflicts import check_conflicts
from .clinic_schedule_card_guard import target_card_sessions
from .models import Location, ScheduleCard, Surgeon
from .practice_time import practice_today
from .or_block_service import log_schedule_change


def schedule_rows_for_slot(query, session: str):
    session = (session or "full").lower()
    if session == "full":
        return query.all()
    return query.filter(ScheduleCard.session == session).all()


def _clear_card(card: ScheduleCard) -> None:
    card.baseline_state = "na"
    card.effective_state = "na"
    card.baseline_location_id = None
    card.effective_location_id = None


def _assign_card(card: ScheduleCard, location_id: int) -> None:
    card.baseline_state = "assigned"
    card.effective_state = "assigned"
    card.baseline_location_id = location_id
    card.effective_location_id = location_id


def assign_clinic(
    db: Session,
    schedule_date: date,
    surgeon_id: int,
    location_choice: str,
    session: str,
    notes: str,
    schedule_id: int | None = None,
) -> list[str]:
    del notes
    if location_choice == "__off__":
        return ["Use Days Off to mark approved OFF time. Blank schedule slots display as NA."]

    sessions = target_card_sessions(session)
    if schedule_id:
        selected_schedule = db.get(ScheduleCard, schedule_id)
        if not selected_schedule:
            return ["Selected clinic/OR assignment was not found. Refresh the page and try again."]
        if selected_schedule.surgeon_id != surgeon_id:
            return ["Selected clinic/OR assignment no longer matches this surgeon. Refresh the page and try again."]
        if selected_schedule.date != schedule_date:
            return ["Selected clinic/OR assignment no longer matches this date. Refresh the page and try again."]
        if selected_schedule.session not in sessions:
            _clear_card(selected_schedule)

    location_id = int(location_choice)
    cards = {
        card.session: card
        for card in db.query(ScheduleCard).filter(
            ScheduleCard.surgeon_id == surgeon_id,
            ScheduleCard.date == schedule_date,
            ScheduleCard.session.in_(sessions),
        ).all()
    }
    if any(card_session not in cards for card_session in sessions):
        return ["This surgeon has no morning or afternoon card for that day."]
    for card_session in sessions:
        _assign_card(cards[card_session], location_id)
    db.commit()
    schedule = cards[sessions[0]]

    surgeon = db.get(Surgeon, surgeon_id)
    loc = db.get(Location, location_id) if location_id else None
    if not surgeon:
        return []
    if not loc:
        return []
    log_schedule_change(
        db,
        event_type="clinic_schedule_updated",
        surgeon_id=surgeon_id,
        event_date=schedule_date,
        title="Clinic/OR schedule updated",
        body=f"{surgeon.initials}: {loc.abbreviation or loc.name} {session.upper()}",
    )
    db.commit()
    # No surgeon push/SMS/email for clinic assigns until notification prefs exist.
    raw = check_conflicts(
        surgeon_id, schedule_date, schedule_date, db,
        exclude_clinic_schedule_id=schedule.id if schedule else None,
        target_entity={"type": "clinic_schedule", "date": schedule_date, "session": session},
    )
    return [f"{surgeon.full_name}: " + conflict for conflict in raw]


def clear_clinic(db: Session, schedule_id: int) -> None:
    card = db.get(ScheduleCard, schedule_id)
    if card:
        _clear_card(card)
        db.commit()


def copy_clinic_week(db: Session, source_offset: int, surgeon_id: str) -> dict:
    today = practice_today()
    src_start = today - timedelta(days=today.weekday()) + timedelta(weeks=source_offset)
    src_end = src_start + timedelta(days=6)
    dst_start = src_start + timedelta(weeks=1)
    dst_end = dst_start + timedelta(days=6)

    src_query = db.query(ScheduleCard).filter(
        ScheduleCard.date >= src_start,
        ScheduleCard.date <= src_end,
        ScheduleCard.effective_state == "assigned",
        ScheduleCard.effective_location_id.isnot(None),
    )
    if surgeon_id != "all":
        try:
            surgeon_filter = int(surgeon_id)
        except ValueError:
            return {"ok": False}
        src_query = src_query.filter(ScheduleCard.surgeon_id == surgeon_filter)

    src_schedules = src_query.all()
    replaced = 0
    created = 0
    for schedule in src_schedules:
        offset = (schedule.date - src_start).days
        new_date = dst_start + timedelta(days=offset)
        dest = db.query(ScheduleCard).filter(
            ScheduleCard.surgeon_id == schedule.surgeon_id,
            ScheduleCard.date == new_date,
            ScheduleCard.session == schedule.session,
        ).one_or_none()
        if dest is None:
            continue
        if dest.effective_state == "assigned":
            replaced += 1
        _assign_card(dest, schedule.effective_location_id)
        created += 1
    db.commit()
    return {"ok": True, "created": created, "replaced": replaced, "next_offset": source_offset + 1}
