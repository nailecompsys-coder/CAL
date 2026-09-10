"""Buffer and location rule checker functions."""
from datetime import date, datetime, timedelta
from typing import Iterator, Optional

from sqlalchemy.orm import Session

from .buffer_helpers import case_end_datetime
from .checker_helpers import target_type
from .registry import Conflict


def check_buffer_clinic_to_surgery(
    surgeon_id: int,
    start_date: date,
    end_date: date,
    db: Session,
    config: dict,
    exclude_entity: Optional[tuple[str, int]] = None,
    target_entity: Optional[dict] = None,
) -> Iterator[Conflict]:
    """Morning clinic then afternoon OR is a normal day. Do not flag the gap."""
    yield from ()


def check_buffer_surgery_to_clinic(
    surgeon_id: int,
    start_date: date,
    end_date: date,
    db: Session,
    config: dict,
    exclude_entity: Optional[tuple[str, int]] = None,
    target_entity: Optional[dict] = None,
) -> Iterator[Conflict]:
    """Block until noon and a 1pm clinic patient is the scheduled day.

    If the surgeon is running late they call the office. CAL does not flag that gap.
    """
    yield from ()


def check_buffer_between_cases(
    surgeon_id: int,
    start_date: date,
    end_date: date,
    db: Session,
    config: dict,
    exclude_entity: Optional[tuple[str, int]] = None,
    target_entity: Optional[dict] = None,
) -> Iterator[Conflict]:
    from ..models import SurgicalCase
    if target_type(target_entity) != "surgical_case":
        return
    minutes = config.get("minutes", 15)
    delta = timedelta(minutes=minutes)
    q = db.query(SurgicalCase).filter(
        SurgicalCase.surgeon_id == surgeon_id,
        SurgicalCase.date >= start_date,
        SurgicalCase.date <= end_date,
        SurgicalCase.status != "cancelled",
    ).order_by(SurgicalCase.date, SurgicalCase.start_time)
    if exclude_entity and exclude_entity[0] == "surgical_case":
        q = q.filter(SurgicalCase.id != exclude_entity[1])
    cases = q.all()
    for i in range(len(cases) - 1):
        a, b = cases[i], cases[i + 1]
        if a.date != b.date:
            continue
        end_a = case_end_datetime(a)
        start_b = datetime.combine(b.date, b.start_time)
        if end_a <= start_b and (start_b - end_a) < delta:
            yield Conflict(
                rule_id="BUFFER_BETWEEN_CASES",
                surgeon_id=surgeon_id,
                date=a.date,
                message=f"Turn time: need {minutes} min between cases ({a.patient_name or 'case'} → {b.patient_name or 'case'})",
                severity="warning",
                conflicting_entity_type="surgical_case",
                conflicting_entity_id=b.id,
            )


def check_buffer_same_site_am_pm(
    surgeon_id: int,
    start_date: date,
    end_date: date,
    db: Session,
    config: dict,
    exclude_entity: Optional[tuple[str, int]] = None,
    target_entity: Optional[dict] = None,
) -> Iterator[Conflict]:
    """AM then PM at the same site is scheduled time, not a CAL travel flag."""
    yield from ()


def check_location_drive_time(
    surgeon_id: int,
    start_date: date,
    end_date: date,
    db: Session,
    config: dict,
    exclude_entity: Optional[tuple[str, int]] = None,
    target_entity: Optional[dict] = None,
) -> Iterator[Conflict]:
    """Hospital AM then office PM is the paper day. Running late is a phone call."""
    yield from ()
