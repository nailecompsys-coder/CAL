"""Rule definitions: id, name, category, default config, and checker function."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, time
from typing import Any, Callable, Iterator, Optional

from sqlalchemy.orm import Session


@dataclass
class Conflict:
    rule_id: str
    surgeon_id: int
    date: date
    message: str
    severity: str = "warning"
    conflicting_entity_type: Optional[str] = None
    conflicting_entity_id: Optional[int] = None

    def to_display_string(self, surgeon_name: Optional[str] = None) -> str:
        if surgeon_name:
            return f"{surgeon_name}: {self.message}"
        return self.message


@dataclass
class RuleDef:
    rule_id: str
    name: str
    category: str  # overlap | buffer | location
    description: str
    default_config: dict
    config_schema: list  # [{"key": "minutes", "type": "number", "label": "Minutes"}]
    checker: Optional[Callable[..., Iterator[Conflict]]] = None


# Default session times for clinic (used by buffer rules).
CLINIC_AM_END = time(12, 0)
CLINIC_PM_START = time(13, 0)
CLINIC_PM_END = time(17, 0)
CLINIC_FULL_END = time(17, 0)


def _session_end_time(session: str) -> time:
    if session == "am":
        return CLINIC_AM_END
    if session == "pm":
        return CLINIC_PM_END
    return CLINIC_FULL_END


def _session_start_time(session: str) -> time:
    if session == "pm":
        return CLINIC_PM_START
    return time(8, 0)


# Populated below after importing checkers
ALL_RULES: list[RuleDef] = []


def _build_rules() -> list[RuleDef]:
    from .checkers import (
        check_buffer_between_cases,
        check_buffer_clinic_to_surgery,
        check_buffer_same_site_am_pm,
        check_buffer_surgery_to_clinic,
        check_location_drive_time,
        check_clinic_group_day_off_capacity,
        check_overlap_call,
        check_overlap_clinic,
        check_overlap_day_off,
        check_overlap_meeting,
        check_overlap_surgery,
        check_overlap_unavailable,
    )
    return [
        RuleDef(
            rule_id="OVERLAP_DAY_OFF",
            name="Day off overlap",
            category="overlap",
            description="Approved day off vs any other commitment that day",
            default_config={},
            config_schema=[],
            checker=check_overlap_day_off,
        ),
        RuleDef(
            rule_id="OVERLAP_CALL",
            name="Call overlap",
            category="overlap",
            description="On-call assignment vs clinic/surgery/day off that day",
            default_config={},
            config_schema=[],
            checker=check_overlap_call,
        ),
        RuleDef(
            rule_id="CLINIC_GROUP_DAY_OFF_CAPACITY",
            name="Clinic group day-off capacity",
            category="overlap",
            description="Warn when approved physicians already off meet the clinic group limit",
            default_config={},
            config_schema=[],
            checker=check_clinic_group_day_off_capacity,
        ),
        RuleDef(
            rule_id="OVERLAP_CLINIC",
            name="Clinic overlap",
            category="overlap",
            description="Two clinic blocks or clinic + surgery at overlapping times",
            default_config={},
            config_schema=[],
            checker=check_overlap_clinic,
        ),
        RuleDef(
            rule_id="OVERLAP_SURGERY",
            name="Surgery overlap",
            category="overlap",
            description="Two surgical cases (same surgeon) at overlapping times",
            default_config={},
            config_schema=[],
            checker=check_overlap_surgery,
        ),
        RuleDef(
            rule_id="OVERLAP_UNAVAILABLE",
            name="Unavailable overlap",
            category="overlap",
            description="Marked unavailable vs any scheduled commitment",
            default_config={},
            config_schema=[],
            checker=check_overlap_unavailable,
        ),
        RuleDef(
            rule_id="OVERLAP_MEETING",
            name="Meeting overlap",
            category="overlap",
            description="Meeting vs clinic/surgery at same time",
            default_config={},
            config_schema=[],
            checker=check_overlap_meeting,
        ),
        RuleDef(
            rule_id="BUFFER_CLINIC_TO_SURGERY",
            name="Clinic → surgery buffer",
            category="buffer",
            description="Minimum minutes between end of clinic and start of first surgery that day",
            default_config={"minutes": 30},
            config_schema=[{"key": "minutes", "type": "number", "label": "Minutes"}],
            checker=check_buffer_clinic_to_surgery,
        ),
        RuleDef(
            rule_id="BUFFER_SURGERY_TO_CLINIC",
            name="Surgery → clinic buffer",
            category="buffer",
            description="Minimum minutes between end of last surgery and start of clinic",
            default_config={"minutes": 30},
            config_schema=[{"key": "minutes", "type": "number", "label": "Minutes"}],
            checker=check_buffer_surgery_to_clinic,
        ),
        RuleDef(
            rule_id="BUFFER_BETWEEN_CASES",
            name="Turn time between cases",
            category="buffer",
            description="Minimum minutes between end of one case and start of next (same surgeon, same day)",
            default_config={"minutes": 15},
            config_schema=[{"key": "minutes", "type": "number", "label": "Minutes"}],
            checker=check_buffer_between_cases,
        ),
        RuleDef(
            rule_id="BUFFER_SAME_SITE_AM_PM",
            name="Same-site AM/PM gap",
            category="buffer",
            description="If clinic AM and surgery PM at same site, minimum gap",
            default_config={"minutes": 30},
            config_schema=[{"key": "minutes", "type": "number", "label": "Minutes"}],
            checker=check_buffer_same_site_am_pm,
        ),
        RuleDef(
            rule_id="LOCATION_DRIVE_TIME",
            name="Drive time between sites",
            category="location",
            description="If clinic at site A and surgery at site B same day, minimum gap (minutes)",
            default_config={"minutes_between_sites": 60},
            config_schema=[{"key": "minutes_between_sites", "type": "number", "label": "Minutes between sites"}],
            checker=check_location_drive_time,
        ),
    ]


# Build once on first import
ALL_RULES.extend(_build_rules())
