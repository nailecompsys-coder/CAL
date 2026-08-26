"""Deep links from admin notification cards to the record that needs fixing."""

from __future__ import annotations

from datetime import date
from urllib.parse import urlencode

from .admin_surgical_schedule_service import week_offset_for_date
from .practice_time import practice_today

_CASE_FIXES = {"missing_time", "missing_block_window"}
_ASSIGN_FIXES = {"clinic_location_not_found", "or_location_not_found"}


def month_offset_for_date(target: date, today: date | None = None) -> int:
    today = today or practice_today()
    return (target.year * 12 + target.month) - (today.year * 12 + today.month)


def _as_int(value) -> int | None:
    try:
        if value is None or value == "":
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _as_date(value) -> date | None:
    if isinstance(value, date):
        return value
    raw = str(value or "").strip()[:10]
    if not raw:
        return None
    try:
        return date.fromisoformat(raw)
    except ValueError:
        return None


def clinic_schedule_fix_href(
    *,
    day: date | None = None,
    surgeon_id: int | None = None,
    case_id: int | None = None,
    reason: str | None = None,
    patient_name: str | None = None,
    procedure: str | None = None,
    site: str | None = None,
    room: str | None = None,
) -> str:
    """Clinic / OR cell for this surgeon and date, with the matching edit modal."""
    params: dict[str, str] = {
        "week_offset": str(week_offset_for_date(day) if day else 0),
    }
    if surgeon_id:
        params["surgeon_id"] = str(surgeon_id)
    if day:
        params["focus_date"] = day.isoformat()
    if case_id:
        params["edit_case"] = str(case_id)
    reason = (reason or "").strip()
    if reason in _CASE_FIXES:
        params["fix"] = "missing_time"
    elif reason == "clinic_location_not_found":
        params["fix"] = "clinic_location"
    elif reason == "or_location_not_found":
        params["fix"] = "or_location"
    elif reason:
        params["fix"] = reason
    if patient_name:
        params["patient"] = str(patient_name)
    if procedure:
        params["procedure"] = str(procedure)
    if site:
        params["site"] = str(site)
    if room:
        params["room"] = str(room)
    return "/admin/clinic-schedule?" + urlencode(params)


def _dayoff_href(payload: dict) -> str:
    day_off_id = _as_int(payload.get("dayOffId") or payload.get("keptId"))
    start = payload.get("startDate")
    end = payload.get("endDate") or start
    if day_off_id and start:
        return f"/admin/daysoff?focus={day_off_id}&gantt_start={start}&gantt_end={end}"
    if day_off_id:
        return f"/admin/daysoff?focus={day_off_id}"
    return "/admin/daysoff"


def _block_or_href(payload: dict) -> str:
    block_id = _as_int(payload.get("blockId"))
    day = _as_date(payload.get("date"))
    if not block_id:
        stored = (payload.get("href") or "").strip()
        return stored or "/admin/block-or"
    params = {"block_id": str(block_id), "panel": "assign"}
    if day:
        params["week_offset"] = str(week_offset_for_date(day))
    return "/admin/block-or?" + urlencode(params)


def _ingest_href(payload: dict) -> str:
    reason = (payload.get("reason") or "").strip()
    extra = (payload.get("extra") or "").strip() or None
    if reason == "surgeon_not_found":
        name = (payload.get("surgeonName") or extra or "").strip()
        qs = urlencode({"add": "1", "name": name}) if name else "add=1"
        return f"/admin/surgeons?{qs}"
    procedure = payload.get("procedure")
    site = payload.get("site")
    room = payload.get("room")
    if reason == "clinic_location_not_found":
        site = site or extra
    elif reason == "or_location_not_found":
        room = room or extra
    elif reason in _CASE_FIXES:
        procedure = procedure or extra
    return clinic_schedule_fix_href(
        day=_as_date(payload.get("date")),
        surgeon_id=_as_int(payload.get("surgeonId")),
        case_id=_as_int(payload.get("caseId")),
        reason=reason,
        patient_name=payload.get("patientName"),
        procedure=procedure,
        site=site,
        room=room,
    )


def _call_href(payload: dict) -> str:
    rotation_id = _as_int(payload.get("rotationId"))
    day = _as_date(payload.get("date"))
    params: dict[str, str] = {}
    if day:
        params["month_offset"] = str(month_offset_for_date(day))
    if rotation_id:
        params["rotation_id"] = str(rotation_id)
    if not params:
        return "/admin/call-schedule"
    return "/admin/call-schedule?" + urlencode(params)


def _rules_href(payload: dict) -> str:
    rule_id = (payload.get("ruleId") or "").strip()
    if rule_id:
        return f"/admin/settings/scheduling-rules#rule-{rule_id}"
    return "/admin/settings/scheduling-rules"


def admin_notification_href(kind: str | None, payload: dict | None) -> str:
    """Return the portal URL that opens the row / modal for this notification."""
    payload = payload if isinstance(payload, dict) else {}
    kind = (kind or "").strip()
    if kind in {"day_off_request", "day_off_duplicate"}:
        return _dayoff_href(payload)
    if kind == "schedule_flag":
        return _block_or_href(payload)
    if kind == "ingest_correction":
        return _ingest_href(payload)
    if kind == "call_coverage_conflict":
        return _call_href(payload)
    if kind == "rules_engine_error":
        return _rules_href(payload)
    return (payload.get("href") or "").strip()
