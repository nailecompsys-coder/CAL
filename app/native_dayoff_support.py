"""Native day-off serialization and section helpers."""

import json
from collections import defaultdict
from datetime import date, timedelta

from fastapi import HTTPException
from sqlalchemy.orm import Session, joinedload

from .models import DayOff, Surgeon
from .native_surgeon_support import native_surgeon_rank_key, native_viewer_sees_physicians
from .native_time_utils import fmt_time, parse_hhmm


def day_off_segments(row: DayOff) -> list[dict]:
    if row.segments:
        try:
            parsed = json.loads(row.segments)
            if isinstance(parsed, list):
                return parsed
        except json.JSONDecodeError:
            pass
    segments = []
    current = row.start_date
    while current <= row.end_date:
        segments.append({
            "date": current.isoformat(),
            "isFullDay": row.is_full_day if row.is_full_day is not None else True,
            "start": fmt_time(row.start_time),
            "end": fmt_time(row.end_time),
        })
        current += timedelta(days=1)
    return segments


def segment_for_date(row: DayOff, day: date) -> dict | None:
    for segment in day_off_segments(row):
        if segment.get("date") == day.isoformat():
            return segment
    return None


def serialize_day_off(row: DayOff) -> dict:
    return {
        "id": row.id,
        "surgeonId": row.surgeon_id,
        "surgeonName": row.surgeon.full_name if row.surgeon else "",
        "surgeonInitials": row.surgeon.initials if row.surgeon else "",
        "surgeonSortOrder": row.surgeon.sort_order if row.surgeon else 0,
        "startDate": row.start_date.isoformat(),
        "endDate": row.end_date.isoformat(),
        "reason": row.reason or "",
        "notes": row.notes or "",
        "adminNote": row.admin_note or "",
        "status": row.status or "pending",
        "isFullDay": row.is_full_day if row.is_full_day is not None else True,
        "start": fmt_time(row.start_time),
        "end": fmt_time(row.end_time),
        "segments": day_off_segments(row),
    }


def normalize_day_off_segments(
    start_date: date,
    end_date: date,
    is_full_day: bool,
    start: str | None,
    end: str | None,
    raw: list | None,
) -> list[dict]:
    by_date = {str(item.get("date")): item for item in raw or [] if isinstance(item, dict)}
    segments = []
    current = start_date
    while current <= end_date:
        item = by_date.get(current.isoformat(), {})
        full = item.get("isFullDay", is_full_day)
        start_value = None if full else (item.get("start") or start)
        end_value = None if full else (item.get("end") or end)
        segments.append({
            "date": current.isoformat(),
            "isFullDay": bool(full),
            "start": start_value,
            "end": end_value,
        })
        current += timedelta(days=1)
    return segments


def validate_day_off_segments(segments: list[dict]) -> None:
    for segment in segments:
        if segment.get("isFullDay"):
            continue
        start_t = parse_hhmm(str(segment.get("start") or ""))
        end_t = parse_hhmm(str(segment.get("end") or ""))
        if not start_t or not end_t or end_t <= start_t:
            raise HTTPException(400, "Partial days need a valid start and end time.")


def months_spanned(start_date: date, end_date: date) -> list[tuple[int, int]]:
    months = []
    cursor = date(start_date.year, start_date.month, 1)
    end_month = date(end_date.year, end_date.month, 1)
    while cursor <= end_month:
        months.append((cursor.year, cursor.month))
        year = cursor.year + (1 if cursor.month == 12 else 0)
        month = 1 if cursor.month == 12 else cursor.month + 1
        cursor = date(year, month, 1)
    return months


def native_day_off_sections(db: Session, viewer: Surgeon) -> list[dict]:
    today = date.today()
    current_month = date(today.year, today.month, 1)
    window_start = current_month - timedelta(days=95)
    discovery_end = today + timedelta(days=730)
    rows = (
        db.query(DayOff)
        .join(Surgeon, DayOff.surgeon_id == Surgeon.id)
        .filter(
            DayOff.status != "denied",
            Surgeon.is_active == True,  # noqa: E712
            DayOff.start_date <= discovery_end,
            DayOff.end_date >= window_start,
        )
        .order_by(DayOff.start_date)
        .options(joinedload(DayOff.surgeon))
        .all()
    )
    months = []
    cursor = date(window_start.year, window_start.month, 1)
    for _ in range(16):
        months.append((cursor.year, cursor.month))
        year = cursor.year + (1 if cursor.month == 12 else 0)
        month = 1 if cursor.month == 12 else cursor.month + 1
        cursor = date(year, month, 1)
    for req in rows:
        ym = (req.start_date.year, req.start_date.month)
        if ym not in months and ym >= months[0]:
            months.append(ym)
    months.sort()

    target_staff_type = "physician" if native_viewer_sees_physicians(viewer) else "staff"
    header_suffix = "SURGEONS" if target_staff_type == "physician" else "PAS"
    by_month: dict[tuple[int, int], list[DayOff]] = defaultdict(list)
    for req in rows:
        if not req.surgeon:
            continue
        if target_staff_type == "physician" and req.surgeon.staff_type != "physician":
            continue
        if target_staff_type != "physician" and req.surgeon.staff_type == "physician":
            continue
        for ym in months_spanned(req.start_date, req.end_date):
            by_month[ym].append(req)
    for requests in by_month.values():
        requests.sort(key=lambda req: (native_surgeon_rank_key(req.surgeon), req.start_date, req.id))
    return [
        {
            "header": f"{date(year, month, 1).strftime('%b').upper()} {header_suffix}",
            "isCurrentMonth": year == today.year and month == today.month,
            "requests": [serialize_day_off(row) for row in by_month.get((year, month), [])],
        }
        for year, month in months
    ]
