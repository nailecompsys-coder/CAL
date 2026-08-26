"""Portal dashboard schedule volume stats (today, all campuses)."""
from __future__ import annotations

from datetime import date

from sqlalchemy.orm import Session

from .admin_clinic_schedule_page_service import parse_clinic_fax_visit_segments
from .aprima_cache_service import patient_appointments_for_api
from .aprima_schedule_service import is_surgery_appointment
from .models import ClinicSchedule, SurgicalCase
from .practice_time import practice_today


def surgical_cases_today_count(db: Session, day: date | None = None) -> int:
    """Non-cancelled SurgicalCase rows for *day* (all locations / campuses)."""
    target = day or practice_today()
    return (
        db.query(SurgicalCase)
        .filter(
            SurgicalCase.date == target,
            SurgicalCase.status != "cancelled",
        )
        .count()
    )


def _fax_clinic_visits_today(db: Session, target: date) -> int:
    schedules = (
        db.query(ClinicSchedule)
        .filter(
            ClinicSchedule.date == target,
            ClinicSchedule.assignment_type != "off",
        )
        .all()
    )
    total = 0
    for row in schedules:
        total += len(parse_clinic_fax_visit_segments(row.notes or ""))
    return total


def clinic_visits_today_count(db: Session, day: date | None = None) -> int:
    """Clinic visits for *day* across campuses.

    Counts Aprima patient appointments that are not Surgery types (all service
    sites) plus Desk fax visit segments on ClinicSchedule notes. Both pipelines
    feed the portal as scheduling lands in CAL.
    """
    target = day or practice_today()
    payload = patient_appointments_for_api(db, target, target, surgeon=None)
    aprima_rows = payload.get("appointments") or []
    aprima_clinic = sum(1 for row in aprima_rows if not is_surgery_appointment(row))
    return aprima_clinic + _fax_clinic_visits_today(db, target)


def dashboard_today_volume_stats(db: Session, day: date | None = None) -> dict:
    target = day or practice_today()
    return {
        "surgical_cases_today": surgical_cases_today_count(db, target),
        "clinic_visits_today": clinic_visits_today_count(db, target),
    }
