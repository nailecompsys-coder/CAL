"""Portal dashboard volume stats from normalized SQL rows."""

from __future__ import annotations

from datetime import date

from sqlalchemy import func
from sqlalchemy.orm import Session

from .models import ScheduleCardActivity
from .practice_time import practice_today


def _activity_count(db: Session, target: date, activity_type: str) -> int:
    return int(
        db.query(func.count(func.distinct(ScheduleCardActivity.identity_key)))
        .filter(
            ScheduleCardActivity.activity_date == target,
            ScheduleCardActivity.activity_type == activity_type,
            ScheduleCardActivity.is_active == True,  # noqa: E712
        )
        .scalar() or 0
    )


def surgical_cases_today_count(db: Session, day: date | None = None) -> int:
    return _activity_count(db, day or practice_today(), "surgical")


def clinic_visits_today_count(db: Session, day: date | None = None) -> int:
    return _activity_count(db, day or practice_today(), "clinic")


def dashboard_today_volume_stats(db: Session, day: date | None = None) -> dict:
    target = day or practice_today()
    return {
        "surgical_cases_today": surgical_cases_today_count(db, target),
        "clinic_visits_today": clinic_visits_today_count(db, target),
    }
