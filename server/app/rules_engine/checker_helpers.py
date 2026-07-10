"""Shared helpers for rule checker functions."""
from datetime import date, datetime, time, timedelta
from typing import Optional

from .registry import _session_end_time, _session_start_time


def exclude_entity(
    exclude_entity: Optional[tuple[str, int]],
    entity_type: str,
    entity_id: int,
) -> bool:
    """True if this entity should be excluded from conflict check."""
    if not exclude_entity:
        return False
    etype, eid = exclude_entity
    return etype == entity_type and eid == entity_id


def target_type(target_entity: Optional[dict]) -> Optional[str]:
    return (target_entity or {}).get("type")


def target_dates(target_entity: Optional[dict], start_date: date, end_date: date) -> tuple[date, date]:
    if not target_entity:
        return start_date, end_date
    return (
        target_entity.get("start_date", target_entity.get("date", start_date)),
        target_entity.get("end_date", target_entity.get("date", end_date)),
    )


def session_range(d: date, session: str | None) -> tuple[datetime, datetime]:
    normalized = (session or "full").lower()
    return (
        datetime.combine(d, _session_start_time(normalized)),
        datetime.combine(d, _session_end_time(normalized)),
    )


def case_range(sc) -> tuple[datetime, datetime]:
    start_dt = datetime.combine(sc.date, sc.start_time)
    end_dt = datetime.combine(sc.date, sc.end_time) if sc.end_time else start_dt + timedelta(hours=1)
    return start_dt, end_dt


def meeting_range(m) -> tuple[datetime, datetime]:
    if m.start_time is None:
        start_dt = datetime.combine(m.date, time(0, 0))
        return start_dt, start_dt + timedelta(days=1)
    start_dt = datetime.combine(m.date, m.start_time)
    end_dt = datetime.combine(m.date, m.end_time) if m.end_time else start_dt + timedelta(hours=1)
    return start_dt, end_dt


def _coerce_time(value) -> Optional[time]:
    if value is None or value == "":
        return None
    if isinstance(value, time):
        return value
    if isinstance(value, datetime):
        return value.time()
    text = str(value).strip()
    if not text:
        return None
    for fmt in ("%H:%M", "%H:%M:%S", "%I:%M %p", "%I:%M%p"):
        try:
            return datetime.strptime(text, fmt).time()
        except ValueError:
            continue
    return None


def day_off_unavailable_range_on_day(
    target_entity: Optional[dict],
    day: date,
) -> Optional[tuple[datetime, datetime]]:
    """
    Unavailable window for a day-off target on `day`.
    None means the surgeon is available that entire day (not off).
    Partial days use segment start/end; full days are 00:00–24:00.
    """
    if not target_entity or target_type(target_entity) != "day_off":
        return None
    start_date = target_entity.get("start_date") or target_entity.get("date")
    end_date = target_entity.get("end_date") or target_entity.get("date")
    if start_date and end_date and (day < start_date or day > end_date):
        return None

    segments = target_entity.get("segments") or []
    segment = None
    for item in segments:
        if not isinstance(item, dict):
            continue
        if str(item.get("date") or "") == day.isoformat():
            segment = item
            break

    if segment is not None:
        if segment.get("isFullDay", True):
            start_dt = datetime.combine(day, time(0, 0))
            return start_dt, start_dt + timedelta(days=1)
        start_t = _coerce_time(segment.get("start"))
        end_t = _coerce_time(segment.get("end"))
        if not start_t or not end_t:
            start_dt = datetime.combine(day, time(0, 0))
            return start_dt, start_dt + timedelta(days=1)
        return datetime.combine(day, start_t), datetime.combine(day, end_t)

    is_full = target_entity.get("is_full_day", True)
    if is_full is None or is_full:
        start_dt = datetime.combine(day, time(0, 0))
        return start_dt, start_dt + timedelta(days=1)
    start_t = _coerce_time(target_entity.get("start_time") or target_entity.get("start"))
    end_t = _coerce_time(target_entity.get("end_time") or target_entity.get("end"))
    if not start_t or not end_t:
        start_dt = datetime.combine(day, time(0, 0))
        return start_dt, start_dt + timedelta(days=1)
    return datetime.combine(day, start_t), datetime.combine(day, end_t)


def target_range_on_day(target_entity: Optional[dict], day: date) -> Optional[tuple[datetime, datetime]]:
    if not target_entity:
        return None
    ttype = target_type(target_entity)
    if ttype == "day_off":
        return day_off_unavailable_range_on_day(target_entity, day)
    if ttype == "clinic_schedule":
        return session_range(day, target_entity.get("session"))
    if ttype == "surgical_case":
        start_t = target_entity.get("start_time")
        if not start_t:
            return None
        start_dt = datetime.combine(day, start_t)
        end_t = target_entity.get("end_time")
        end_dt = datetime.combine(day, end_t) if end_t else start_dt + timedelta(hours=1)
        return start_dt, end_dt
    if ttype == "meeting":
        start_t = target_entity.get("start_time")
        if start_t is None:
            start_dt = datetime.combine(day, time(0, 0))
            return start_dt, start_dt + timedelta(days=1)
        start_dt = datetime.combine(day, start_t)
        end_t = target_entity.get("end_time")
        end_dt = datetime.combine(day, end_t) if end_t else start_dt + timedelta(hours=1)
        return start_dt, end_dt
    if ttype in {"or_block", "call_rotation", "call_coverage"}:
        start_t = target_entity.get("start_time")
        end_t = target_entity.get("end_time")
        if start_t is None:
            start_dt = datetime.combine(day, time(0, 0))
            return start_dt, start_dt + timedelta(days=1)
        start_dt = datetime.combine(day, start_t)
        end_dt = datetime.combine(day, end_t) if end_t else start_dt + timedelta(hours=12)
        return start_dt, end_dt
    return None


def ranges_overlap(a_start: datetime, a_end: datetime, b_start: datetime, b_end: datetime) -> bool:
    return a_start < b_end and b_start < a_end
