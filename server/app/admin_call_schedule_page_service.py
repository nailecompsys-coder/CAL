from __future__ import annotations

import calendar as calendar_lib
from datetime import date, timedelta

from sqlalchemy.orm import Session, joinedload

from .models import CallCoverage, CallGroup, CallGroupLocation, CallRotation, DayOff, Location, Surgeon
from .practice_time import practice_today
from .surgeon_visibility import surgeon_is_visible


def parse_call_group_id(raw: str | int | None) -> int | None:
    if raw is None:
        return None
    if isinstance(raw, int):
        return raw
    value = (raw or "").strip()
    return int(value) if value else None


def month_schedule_days(month_offset: int) -> dict:
    today = practice_today()
    total_months = today.year * 12 + (today.month - 1) + month_offset
    year = total_months // 12
    month = total_months % 12 + 1
    first_day = date(year, month, 1)
    days_in_month = calendar_lib.monthrange(year, month)[1]
    schedule_days = [date(year, month, day) for day in range(1, days_in_month + 1)]
    return {
        "today": today,
        "schedule_days": schedule_days,
        "month_label": first_day.strftime("%B %Y"),
        "pad_start": (first_day.weekday() + 1) % 7,
    }


def day_off_by_date(db: Session, schedule_days: list[date], surgeon_sort_key) -> dict[date, dict[str, list[Surgeon]]]:
    day_off_rows = (
        db.query(DayOff)
        .options(joinedload(DayOff.surgeon))
        .filter(
            DayOff.start_date <= schedule_days[-1],
            DayOff.end_date >= schedule_days[0],
            DayOff.status.in_(["pending", "approved"]),
        )
        .all()
    )
    by_date: dict[date, dict[str, list[Surgeon]]] = {
        day: {"pending": [], "approved": []} for day in schedule_days
    }
    seen_initials: dict[date, dict[str, set[str]]] = {
        day: {"pending": set(), "approved": set()} for day in schedule_days
    }
    for row in day_off_rows:
        if not surgeon_is_visible(row.surgeon):
            continue
        status = "approved" if row.status == "approved" else "pending"
        current = max(row.start_date, schedule_days[0])
        end = min(row.end_date, schedule_days[-1])
        while current <= end:
            initials = (row.surgeon.initials or "").strip()
            if initials and initials not in seen_initials[current][status]:
                by_date[current][status].append(row.surgeon)
                seen_initials[current][status].add(initials)
            current += timedelta(days=1)
    for status_groups in by_date.values():
        for surgeons_for_status in status_groups.values():
            surgeons_for_status.sort(key=surgeon_sort_key)
    return by_date


def call_group_display_color(call_group: CallGroup) -> str:
    """Use the group's linked facility color (WG-OR / AL-OR), not hardcoded pastels."""
    locations = [
        link.location
        for link in (call_group.locations or [])
        if link.location and link.location.is_active
    ]
    if not locations:
        return "#cbd5e1"
    hospitals = [loc for loc in locations if (loc.location_type or "") == "hospital"]
    preferred = hospitals or locations
    # Prefer primary OR abbreviations when present (WG-OR, AL-OR).
    for abbr in ("WG-OR", "AL-OR"):
        for loc in preferred:
            if (loc.abbreviation or "").upper() == abbr and loc.color:
                return loc.color
    for loc in preferred:
        if loc.color:
            return loc.color
    return "#cbd5e1"


def call_group_rows(db: Session, call_groups: list[CallGroup], schedule_days: list[date]) -> list[tuple[CallGroup, dict]]:
    rotations = (
        db.query(CallRotation)
        .options(
            joinedload(CallRotation.surgeon),
            joinedload(CallRotation.coverages).joinedload(CallCoverage.covering_surgeon),
        )
        .filter(
            CallRotation.date >= schedule_days[0],
            CallRotation.date <= schedule_days[-1],
        )
        .all()
    )

    rotation_by_group_date = {}
    for rotation in rotations:
        if rotation.call_group_id is None:
            continue
        if rotation.surgeon and not surgeon_is_visible(rotation.surgeon):
            continue
        by_date = rotation_by_group_date.setdefault(rotation.call_group_id, {})
        if rotation.date not in by_date:
            by_date[rotation.date] = rotation

    seen_names = set()
    rows = []
    for call_group in call_groups:
        if call_group.name in seen_names:
            continue
        seen_names.add(call_group.name)
        merged_rotations = dict(rotation_by_group_date.get(call_group.id, {}))
        for other in call_groups:
            if other.id != call_group.id and other.name == call_group.name:
                for day, rotation in rotation_by_group_date.get(other.id, {}).items():
                    if day not in merged_rotations:
                        merged_rotations[day] = rotation
        rows.append((call_group, merged_rotations))
    return rows


def page_data(db: Session, month_offset: int, surgeon_sort_key) -> dict:
    month_data = month_schedule_days(month_offset)
    schedule_days = month_data["schedule_days"]
    call_groups = (
        db.query(CallGroup)
        .options(joinedload(CallGroup.locations).joinedload(CallGroupLocation.location))
        .order_by(CallGroup.sort_order, CallGroup.name, CallGroup.id)
        .all()
    )
    return {
        **month_data,
        "group_rows": call_group_rows(db, call_groups, schedule_days),
        "day_off_by_date": day_off_by_date(db, schedule_days, surgeon_sort_key),
        "call_groups": call_groups,
        "call_group_display_color": call_group_display_color,
        "locations": db.query(Location).filter(Location.is_active == True).order_by(Location.name).all(),  # noqa: E712
        "surgeon_is_visible": surgeon_is_visible,
    }
