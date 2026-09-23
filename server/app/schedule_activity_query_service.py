"""SQL-only aggregates over normalized schedule activity rows."""

from __future__ import annotations

from datetime import date

from sqlalchemy import func
from sqlalchemy.orm import Session

from .models import ScheduleCardActivity


def activity_counts_by_card(
    db: Session,
    start: date,
    end: date,
) -> dict[tuple[int, str], int]:
    rows = (
        db.query(
            ScheduleCardActivity.schedule_card_id,
            ScheduleCardActivity.activity_type,
            func.count(func.distinct(ScheduleCardActivity.identity_key)),
        )
        .filter(
            ScheduleCardActivity.activity_date >= start,
            ScheduleCardActivity.activity_date <= end,
            ScheduleCardActivity.is_active == True,  # noqa: E712
        )
        .group_by(
            ScheduleCardActivity.schedule_card_id,
            ScheduleCardActivity.activity_type,
        )
        .all()
    )
    return {(card_id, activity_type): int(total) for card_id, activity_type, total in rows}
