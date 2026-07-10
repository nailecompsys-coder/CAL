from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Optional

from .checker_helpers import (
    day_off_unavailable_range_on_day,
    ranges_overlap,
    target_dates,
    target_range_on_day,
    target_type,
)


@dataclass(frozen=True)
class OverlapTarget:
    kind: Optional[str]
    start: date
    end: date
    day: Optional[date]
    range: Optional[tuple]
    entity: Optional[dict] = None


def overlap_target(target_entity: Optional[dict], start_date: date, end_date: date) -> OverlapTarget:
    target_start, target_end = target_dates(target_entity, start_date, end_date)
    target_day = target_entity.get("date") if target_entity else None
    return OverlapTarget(
        kind=target_type(target_entity),
        start=target_start,
        end=target_end,
        day=target_day,
        range=target_range_on_day(target_entity, target_day) if target_day else None,
        entity=target_entity,
    )


def should_skip_time_overlap(
    target: OverlapTarget,
    row_date,
    row_range: tuple,
    target_kinds: set[str],
) -> bool:
    """
    Return True when the row does not conflict with the target window.
    Day-off targets are multi-day and use per-day unavailable ranges from segments.
    """
    if target.kind == "day_off" and target.entity:
        off_range = day_off_unavailable_range_on_day(target.entity, row_date)
        if off_range is None:
            return True
        return not ranges_overlap(off_range[0], off_range[1], row_range[0], row_range[1])

    if target.kind not in target_kinds:
        return False
    if not target.day or row_date != target.day or not target.range:
        return True
    return not ranges_overlap(row_range[0], row_range[1], target.range[0], target.range[1])
