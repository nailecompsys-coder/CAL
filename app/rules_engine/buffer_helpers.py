from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy.orm import Session


def clinic_rows_for_surgeon(db: Session, surgeon_id: int, start_date, end_date):
    from ..models import ClinicSchedule

    return db.query(ClinicSchedule).filter(
        ClinicSchedule.surgeon_id == surgeon_id,
        ClinicSchedule.date >= start_date,
        ClinicSchedule.date <= end_date,
    ).all()


def surgery_rows_for_surgeon(
    db: Session,
    surgeon_id: int,
    start_date,
    end_date,
    exclude_entity: Optional[tuple[str, int]] = None,
):
    from ..models import SurgicalCase

    surgeries = db.query(SurgicalCase).filter(
        SurgicalCase.surgeon_id == surgeon_id,
        SurgicalCase.date >= start_date,
        SurgicalCase.date <= end_date,
        SurgicalCase.status != "cancelled",
    )
    if exclude_entity and exclude_entity[0] == "surgical_case":
        surgeries = surgeries.filter(SurgicalCase.id != exclude_entity[1])
    return surgeries.all()


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
