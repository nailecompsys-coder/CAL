"""Compatibility exports for admin clinic schedule services."""

from .admin_clinic_schedule_action_service import (
    assign_clinic,
    clear_clinic,
    copy_clinic_week,
    schedule_rows_for_slot,
)
from .admin_clinic_schedule_page_service import (
    page_data,
    surgical_case_json,
    week_days_for_offset,
)

__all__ = [
    "assign_clinic",
    "clear_clinic",
    "copy_clinic_week",
    "page_data",
    "schedule_rows_for_slot",
    "surgical_case_json",
    "week_days_for_offset",
]
