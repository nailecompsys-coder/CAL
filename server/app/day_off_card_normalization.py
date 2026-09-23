"""Normalize time-off requests onto permanent AM/PM cards at write time."""

from __future__ import annotations

from datetime import date, time

from sqlalchemy.orm import Session

from .models import DayOff, DayOffScheduleCard, ScheduleCard
from .native_dayoff_support import segment_for_date


def _covers_session(day_off: DayOff, day: date, session: str) -> bool:
    segment = segment_for_date(day_off, day) or {}
    if segment.get("isFullDay", day_off.is_full_day if day_off.is_full_day is not None else True):
        return True
    start = segment.get("start") or (day_off.start_time.strftime("%H:%M") if day_off.start_time else "")
    end = segment.get("end") or (day_off.end_time.strftime("%H:%M") if day_off.end_time else "")
    try:
        start_time = time.fromisoformat(start)
        end_time = time.fromisoformat(end)
    except ValueError:
        return False
    return start_time < time(12, 0) if session == "am" else end_time > time(12, 0)


def sync_day_off_card_links(db: Session, day_off: DayOff) -> int:
    db.query(DayOffScheduleCard).filter(
        DayOffScheduleCard.day_off_id == day_off.id,
    ).delete(synchronize_session=False)
    cards = db.query(ScheduleCard).filter(
        ScheduleCard.surgeon_id == day_off.surgeon_id,
        ScheduleCard.date >= day_off.start_date,
        ScheduleCard.date <= day_off.end_date,
    ).all()
    links = [
        DayOffScheduleCard(day_off_id=day_off.id, schedule_card_id=card.id)
        for card in cards
        if _covers_session(day_off, card.date, card.session)
    ]
    db.add_all(links)
    db.flush()
    return len(links)


def backfill_day_off_card_links(db: Session) -> int:
    linked_ids = {value for (value,) in db.query(DayOffScheduleCard.day_off_id).distinct().all()}
    total = 0
    query = db.query(DayOff)
    if linked_ids:
        query = query.filter(~DayOff.id.in_(linked_ids))
    for day_off in query.all():
        total += sync_day_off_card_links(db, day_off)
    db.commit()
    return total


def sync_day_off_links_for_range(db: Session, start: date, end: date) -> int:
    total = 0
    for day_off in db.query(DayOff).filter(
        DayOff.start_date <= end,
        DayOff.end_date >= start,
    ).all():
        total += sync_day_off_card_links(db, day_off)
    db.flush()
    return total
