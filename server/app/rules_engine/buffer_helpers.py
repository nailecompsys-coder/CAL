from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy.orm import Session


def clinic_rows_for_surgeon(db: Session, surgeon_id: int, start_date, end_date):
    from ..clinic_schedule_card_guard import place_cards
    from ..models import ScheduleCard

    return place_cards(
        db,
        ScheduleCard.surgeon_id == surgeon_id,
        ScheduleCard.date >= start_date,
        ScheduleCard.date <= end_date,
        ScheduleCard.effective_state.in_(("assigned", "off")),
    )


def surgery_rows_for_surgeon(
    db: Session,
    surgeon_id: int,
    start_date,
    end_date,
    exclude_entity: Optional[tuple[str, int]] = None,
):
    from ..schedule_activity_normalization import active_surgical_lines

    exclude_activity_id = (
        exclude_entity[1]
        if exclude_entity and exclude_entity[0] in {"surgical_case", "schedule_card_activity"}
        else None
    )
    return active_surgical_lines(
        db,
        surgeon_id=surgeon_id,
        start=start_date,
        end=end_date,
        exclude_activity_id=exclude_activity_id,
    )


def clinic_and_surgery_rows(
    db: Session,
    surgeon_id: int,
    start_date,
    end_date,
    exclude_entity: Optional[tuple[str, int]] = None,
):
    return (
        clinic_rows_for_surgeon(db, surgeon_id, start_date, end_date),
        surgery_rows_for_surgeon(db, surgeon_id, start_date, end_date, exclude_entity),
    )


def case_end_datetime(case):
    if case.end_time:
        return datetime.combine(case.date, case.end_time)
    return datetime.combine(case.date, case.start_time) + timedelta(hours=1)
