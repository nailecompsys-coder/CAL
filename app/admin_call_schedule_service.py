"""Compatibility exports for admin call schedule services."""

from .admin_call_schedule_action_service import (
    assign_rotation,
    clear_rotation,
    copy_call_week,
    rotation_query_for_assignment,
)
from .admin_call_schedule_page_service import (
    call_group_rows,
    day_off_by_date,
    month_schedule_days,
    page_data,
    parse_call_group_id,
)

__all__ = [
    "assign_rotation",
    "call_group_rows",
    "clear_rotation",
    "copy_call_week",
    "day_off_by_date",
    "month_schedule_days",
    "page_data",
    "parse_call_group_id",
    "rotation_query_for_assignment",
]
