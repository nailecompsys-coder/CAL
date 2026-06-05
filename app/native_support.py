"""Compatibility exports for native iOS API helpers."""

from .native_call_support import active_coverage_for_rotation, serialize_call_assignment
from .native_dayoff_support import (
    day_off_segments,
    months_spanned,
    native_day_off_sections,
    normalize_day_off_segments,
    segment_for_date,
    serialize_day_off,
    validate_day_off_segments,
)
from .native_event_support import meetings_for_surgeon, serialize_native_alert
from .native_surgeon_support import native_surgeon_rank_key, native_viewer_sees_physicians
from .native_time_utils import date_label, fmt_time, parse_hhmm, session_times

__all__ = [
    "active_coverage_for_rotation",
    "date_label",
    "day_off_segments",
    "fmt_time",
    "meetings_for_surgeon",
    "months_spanned",
    "native_day_off_sections",
    "native_surgeon_rank_key",
    "native_viewer_sees_physicians",
    "normalize_day_off_segments",
    "parse_hhmm",
    "segment_for_date",
    "serialize_call_assignment",
    "serialize_day_off",
    "serialize_native_alert",
    "session_times",
    "validate_day_off_segments",
]
