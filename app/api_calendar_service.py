"""Compatibility exports for calendar API event builders."""

from .api_calendar_admin_service import build_admin_calendar_events
from .api_calendar_surgeon_service import build_surgeon_calendar_events
from .api_calendar_utils import (
    NEUTRAL_CAL_BG,
    NEUTRAL_CAL_TEXT,
    SORT_CALL,
    SORT_CLINIC,
    SORT_DAYOFF,
    SORT_MTG,
    SORT_NOCALL,
    SORT_SURG,
    call_group_abbrev,
    location_abbrev,
    pastel_from_location_hex,
    surgeon_initials,
)

__all__ = [
    "NEUTRAL_CAL_BG",
    "NEUTRAL_CAL_TEXT",
    "SORT_CALL",
    "SORT_CLINIC",
    "SORT_DAYOFF",
    "SORT_MTG",
    "SORT_NOCALL",
    "SORT_SURG",
    "build_admin_calendar_events",
    "build_surgeon_calendar_events",
    "call_group_abbrev",
    "location_abbrev",
    "pastel_from_location_hex",
    "surgeon_initials",
]
