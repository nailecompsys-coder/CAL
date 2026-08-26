from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from fastapi import HTTPException
from sqlalchemy.orm import Session

from .models import DayOff
from .native_support import normalize_day_off_segments, parse_hhmm, validate_day_off_segments
from .practice_time import practice_today


@dataclass(frozen=True)
class NativeRequestOffInput:
    start_date: date
    end_date: date
    reason: str = ""
    notes: str = ""
    is_full_day: bool = True
    start: str | None = None
    end: str | None = None
    segments: list[dict] | None = None


def validate_request_dates(start_date: date, end_date: date, action: str) -> None:
    today = practice_today()
    if start_date < today or end_date < today:
        raise HTTPException(400, f"Days off can only be {action} for today or later.")
    if end_date < start_date:
        raise HTTPException(400, "End date must be the same day or after the start date.")


def request_segments(payload: NativeRequestOffInput) -> tuple[list[dict], object, object]:
    segments = normalize_day_off_segments(
        payload.start_date,
        payload.end_date,
        payload.is_full_day,
        payload.start,
        payload.end,
        payload.segments,
    )
    validate_day_off_segments(segments)
    first_partial = next((s for s in segments if not s.get("isFullDay")), None)
    start_t = parse_hhmm(first_partial.get("start")) if first_partial else None
    end_t = parse_hhmm(first_partial.get("end")) if first_partial else None
    return segments, start_t, end_t


def overlapping_request(
    db: Session,
    surgeon_id: int,
    start_date: date,
    end_date: date,
    exclude_id: int | None = None,
) -> DayOff | None:
    query = db.query(DayOff).filter(
        DayOff.surgeon_id == surgeon_id,
        DayOff.status.in_(["pending", "approved"]),
        DayOff.start_date <= end_date,
        DayOff.end_date >= start_date,
    )
    if exclude_id is not None:
        query = query.filter(DayOff.id != exclude_id)
    return query.first()
