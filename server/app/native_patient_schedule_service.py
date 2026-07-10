"""Backward-compatible re-export of Aprima patient schedule helpers.

Prefer importing from ``aprima_schedule_service`` for new code.
"""
from .aprima_schedule_service import (  # noqa: F401
    APPOINTMENT_SQL,
    AprimaScheduleUnavailable,
    _local_bounds_for_dates,
    _serialize_row,
    appointment_belongs_to_surgeon,
    native_patient_schedule,
)
