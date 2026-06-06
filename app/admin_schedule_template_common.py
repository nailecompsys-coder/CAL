from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy.orm import Session

from .models import DayOff, Surgeon


def active_surgeon_ids(db: Session) -> list[int]:
    return [s.id for s in db.query(Surgeon.id).filter(Surgeon.is_active == True).all()]


def parse_target_surgeon_ids(db: Session, surgeon_ids: str) -> list[int]:
    if surgeon_ids == "all":
        return active_surgeon_ids(db)
    return [int(x) for x in surgeon_ids.split(",") if x.strip().isdigit()]


def approved_off_dates(db: Session, surgeon_ids: list[int], start_date, end_date) -> set[tuple[int, object]]:
    days_off_records = db.query(DayOff).filter(
        DayOff.surgeon_id.in_(surgeon_ids),
        DayOff.start_date <= end_date,
        DayOff.end_date >= start_date,
        DayOff.status == "approved",
    ).all()
    off_dates = set()
    for day_off in days_off_records:
        cur = day_off.start_date
        while cur <= day_off.end_date:
            off_dates.add((day_off.surgeon_id, cur))
            cur += timedelta(days=1)
    return off_dates


def parse_date_range(date_from: str, date_to: str):
    try:
        d_from = date.fromisoformat(date_from)
        d_to = date.fromisoformat(date_to)
    except ValueError:
        return None, None, "bad_date"
    if d_to < d_from or (d_to - d_from).days > 366:
        return None, None, "bad_range"
    return d_from, d_to, None
