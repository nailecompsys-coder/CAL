"""Named rules for Desk fax ingest dates.

INGEST_DATE_IN_FAX_WINDOW
  A case or clinic date must fall on or after the fax group's start and on or
  before its end. Fax-group dates are the week (or span) printed on the fax —
  never a patient DOB column that OCR treated as a surgery date.

INGEST_DATE_PLAUSIBLE
  Even before a group window is known, reject years that cannot be a live
  schedule (DOB-like 1954/1965, or 2048 from a bad 2-digit year).

Re-check these on every ingest and when the admin feed loads. Do not treat the
first OCR pass as fact.
"""
from __future__ import annotations

import re
from datetime import date, timedelta
from typing import Any

from .practice_time import practice_today

INGEST_DATE_IN_FAX_WINDOW = "INGEST_DATE_IN_FAX_WINDOW"
INGEST_DATE_PLAUSIBLE = "INGEST_DATE_PLAUSIBLE"

# How far a live OR/clinic date may sit from today when inferring the fax week.
HORIZON_PAST_DAYS = 14
HORIZON_FUTURE_DAYS = 180

_DESK_FAX_RE = re.compile(r"Desk fax\s*#\s*(\d+)", re.IGNORECASE)


def parse_iso_date(raw: str | None) -> date | None:
    if not raw or not str(raw).strip():
        return None
    try:
        return date.fromisoformat(str(raw).strip()[:10])
    except ValueError:
        return None


def plausible_schedule_date(day: date | None, today: date | None = None) -> bool:
    """True when this could be a real schedule day, not a DOB or OCR year."""
    if day is None:
        return False
    today = today or practice_today()
    return today - timedelta(days=HORIZON_PAST_DAYS) <= day <= today + timedelta(days=HORIZON_FUTURE_DAYS)


def infer_fax_group_window(
    surgeons: list[dict[str, Any]],
    *,
    today: date | None = None,
    window_start: date | None = None,
    window_end: date | None = None,
) -> tuple[date, date] | None:
    """Fax-group dates: the span Desk meant to publish, never the outlier DOBs."""
    today = today or practice_today()
    declared: list[date] = []
    for day in (window_start, window_end):
        if day:
            declared.append(day)
    cases: list[date] = []
    for block in surgeons or []:
        start = parse_iso_date(block.get("start_date"))
        end = parse_iso_date(block.get("end_date"))
        if start:
            declared.append(start)
        if end:
            declared.append(end)
        or_block = block.get("or_block") or {}
        for case in or_block.get("cases") or []:
            day = parse_iso_date(case.get("case_date") or block.get("start_date"))
            if day and plausible_schedule_date(day, today):
                cases.append(day)
        clinic = block.get("clinic_rotation") or {}
        for slot in clinic.get("slots") or []:
            day = parse_iso_date(slot.get("case_date") or block.get("start_date"))
            if day and plausible_schedule_date(day, today):
                cases.append(day)
    pool = declared or cases
    if not pool:
        return None
    return min(pool), max(pool)


def snap_date_into_fax_window(
    day: date | None,
    window: tuple[date, date] | None,
    *,
    today: date | None = None,
) -> date | None:
    """Keep a date that is already in the fax week; otherwise try the fax year.

    08-27-28 as 2028-08-27 snaps to 2026-08-27 when the fax is that week.
    07-27-65 as 1965-07-27 is a DOB and is rejected.
    """
    today = today or practice_today()
    if day is None:
        return None
    if window is None:
        return day if plausible_schedule_date(day, today) else None
    start, end = window
    if start <= day <= end:
        return day
    # Patient DOB years must not be rewritten onto the fax week.
    if day.year < min(start.year, end.year) - 1:
        return None
    years = {start.year, end.year}
    for year in years:
        try:
            snapped = day.replace(year=year)
        except ValueError:
            continue
        if start <= snapped <= end:
            return snapped
    return None


def date_allowed_for_fax(
    day: date | None,
    window: tuple[date, date] | None,
    *,
    today: date | None = None,
) -> date | None:
    """Apply INGEST_DATE_IN_FAX_WINDOW (and plausible, if no window yet)."""
    snapped = snap_date_into_fax_window(day, window, today=today)
    if snapped is None:
        return None
    if window is None:
        return snapped if plausible_schedule_date(snapped, today) else None
    start, end = window
    if start <= snapped <= end:
        return snapped
    return None


def looks_like_patient_dob(
    day: date | None,
    window: tuple[date, date] | None,
    *,
    today: date | None = None,
) -> bool:
    """True when a parsed 'case date' is a birthday, not a surgery day.

    If the fax is a week in 2026 and the date is 40+ years earlier (1952, 1965),
    that is a DOB. Younger DOBs (2006) are still before the fax year.
    """
    if day is None:
        return False
    today = today or practice_today()
    if window:
        window_year = min(window[0].year, window[1].year)
        return day.year <= window_year - 40 or day.year < window_year - 1
    return day.year < today.year - 1


def format_dob_display(day: date | None) -> str:
    if day is None:
        return ""
    return day.strftime("%m-%d-%y")


def desk_fax_id_from_notes(notes: str | None) -> int | None:
    match = _DESK_FAX_RE.search(notes or "")
    if not match:
        return None
    try:
        return int(match.group(1))
    except (TypeError, ValueError):
        return None


def patient_name_key(name: str | None) -> str:
    return re.sub(r"[^a-z]", "", (name or "").lower())
