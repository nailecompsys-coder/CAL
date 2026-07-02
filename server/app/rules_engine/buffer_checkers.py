"""Buffer and location rule checker functions."""
from datetime import date, datetime, timedelta
from typing import Iterator, Optional

from sqlalchemy.orm import Session

from .buffer_helpers import case_end_datetime, clinic_and_surgery_rows
from .checker_helpers import target_type
from .registry import CLINIC_AM_END, Conflict, _session_end_time, _session_start_time


def check_buffer_clinic_to_surgery(
    surgeon_id: int,
    start_date: date,
    end_date: date,
    db: Session,
    config: dict,
    exclude_entity: Optional[tuple[str, int]] = None,
    target_entity: Optional[dict] = None,
) -> Iterator[Conflict]:
    if target_type(target_entity) not in {"clinic_schedule", "surgical_case"}:
        return
    minutes = config.get("minutes", 30)
    delta = timedelta(minutes=minutes)
    clinics, surgeries = clinic_and_surgery_rows(db, surgeon_id, start_date, end_date, exclude_entity)
    for sc in surgeries:
        case_start = datetime.combine(sc.date, sc.start_time)
        for cs in clinics:
            if cs.date != sc.date:
                continue
            end_t = _session_end_time(cs.session or "full")
            clinic_end = datetime.combine(cs.date, end_t)
            if clinic_end <= case_start and (case_start - clinic_end) < delta:
                yield Conflict(
                    rule_id="BUFFER_CLINIC_TO_SURGERY",
                    surgeon_id=surgeon_id,
                    date=sc.date,
                    message=f"Clinic then surgery: need {minutes} min between clinic end and surgery start (case: {sc.patient_name or 'surgery'})",
                    severity="warning",
                    conflicting_entity_type="surgical_case",
                    conflicting_entity_id=sc.id,
                )


def check_buffer_surgery_to_clinic(
    surgeon_id: int,
    start_date: date,
    end_date: date,
    db: Session,
    config: dict,
    exclude_entity: Optional[tuple[str, int]] = None,
    target_entity: Optional[dict] = None,
) -> Iterator[Conflict]:
    if target_type(target_entity) not in {"clinic_schedule", "surgical_case"}:
        return
    minutes = config.get("minutes", 30)
    delta = timedelta(minutes=minutes)
    clinics, surgeries = clinic_and_surgery_rows(db, surgeon_id, start_date, end_date, exclude_entity)
    for cs in clinics:
        clinic_start = datetime.combine(cs.date, _session_start_time(cs.session or "full"))
        for sc in surgeries:
            if sc.date != cs.date:
                continue
            case_end = case_end_datetime(sc)
            if case_end <= clinic_start and (clinic_start - case_end) < delta:
                yield Conflict(
                    rule_id="BUFFER_SURGERY_TO_CLINIC",
                    surgeon_id=surgeon_id,
                    date=cs.date,
                    message=f"Surgery then clinic: need {minutes} min between last surgery and clinic start ({cs.location.name if cs.location else 'clinic'})",
                    severity="warning",
                    conflicting_entity_type="clinic_schedule",
                    conflicting_entity_id=cs.id,
                )


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
    if target_type(target_entity) not in {"clinic_schedule", "surgical_case"}:
        return
    minutes = config.get("minutes", 30)
    delta = timedelta(minutes=minutes)
    clinics, surgeries = clinic_and_surgery_rows(db, surgeon_id, start_date, end_date, exclude_entity)
    for cs in clinics:
        if (cs.session or "").lower() != "am":
            continue
        for sc in surgeries:
            if sc.date != cs.date or not sc.location_id or not cs.location_id:
                continue
            if sc.location_id != cs.location_id:
                continue
            clinic_end = datetime.combine(cs.date, CLINIC_AM_END)
            case_start = datetime.combine(sc.date, sc.start_time)
            if case_start > clinic_end and (case_start - clinic_end) < delta:
                yield Conflict(
                    rule_id="BUFFER_SAME_SITE_AM_PM",
                    surgeon_id=surgeon_id,
                    date=cs.date,
                    message=f"Same site AM clinic → PM surgery: need {minutes} min gap at {cs.location.name if cs.location else 'same site'}",
                    severity="warning",
                    conflicting_entity_type="surgical_case",
                    conflicting_entity_id=sc.id,
                )


def check_location_drive_time(
    surgeon_id: int,
    start_date: date,
    end_date: date,
    db: Session,
    config: dict,
    exclude_entity: Optional[tuple[str, int]] = None,
    target_entity: Optional[dict] = None,
) -> Iterator[Conflict]:
    if target_type(target_entity) not in {"clinic_schedule", "surgical_case"}:
        return
    minutes = config.get("minutes_between_sites", 60)
    delta = timedelta(minutes=minutes)
    clinics, surgeries = clinic_and_surgery_rows(db, surgeon_id, start_date, end_date, exclude_entity)
    for cs in clinics:
        for sc in surgeries:
            if sc.date != cs.date or not sc.location_id or not cs.location_id:
                continue
            if sc.location_id == cs.location_id:
                continue
            clinic_end = datetime.combine(cs.date, _session_end_time(cs.session or "full"))
            case_start = datetime.combine(sc.date, sc.start_time)
            if case_start > clinic_end and (case_start - clinic_end) < delta:
                yield Conflict(
                    rule_id="LOCATION_DRIVE_TIME",
                    surgeon_id=surgeon_id,
                    date=sc.date,
                    message=f"Different sites same day: allow {minutes} min between clinic and surgery at different location",
                    severity="warning",
                    conflicting_entity_type="surgical_case",
                    conflicting_entity_id=sc.id,
                )
