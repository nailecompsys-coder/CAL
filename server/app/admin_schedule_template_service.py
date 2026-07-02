"""Compatibility exports for admin schedule template services."""

from .admin_schedule_template_call_service import (
    auto_fill_call_rotation,
    call_rotation_result_url,
    call_rotation_template,
    save_call_rotation_order,
)
from .admin_schedule_template_clinic_service import (
    apply_clinic_schedule_templates,
    clinic_apply_result_url,
    save_template_cell_value,
    template_cells_by_surgeon,
    template_grid_context,
)
from .admin_schedule_template_common import (
    active_surgeon_ids,
    approved_off_dates,
    parse_date_range,
    parse_target_surgeon_ids,
)

__all__ = [
    "active_surgeon_ids",
    "apply_clinic_schedule_templates",
    "approved_off_dates",
    "auto_fill_call_rotation",
    "call_rotation_result_url",
    "call_rotation_template",
    "clinic_apply_result_url",
    "parse_date_range",
    "parse_target_surgeon_ids",
    "save_call_rotation_order",
    "save_template_cell_value",
    "template_cells_by_surgeon",
    "template_grid_context",
]
