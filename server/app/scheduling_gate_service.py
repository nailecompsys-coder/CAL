"""Central scheduling gate: duplicates, conflict review, forward-only evaluation helpers."""

from __future__ import annotations

import json
import logging
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from .conflicts import check_conflicts_structured
from .models import DayOff, Surgeon
from .push import notify_admins, send_native_push_to_surgeon, send_push_to_surgeon
from .scheduling_guardrails_service import DayOffFinding, encode_findings, finding_dicts

log = logging.getLogger(__name__)

PRACTICE_TZ = ZoneInfo("America/New_York")

DUPLICATE_REJECT_MESSAGE = (
    "These dates overlap an existing time-off request. "
    "You can cancel or edit the older one, or leave both — Shannon will sort it out."
)

# Kept as alias for older call sites / tests.
OVERLAP_ADVISORY_MESSAGE = DUPLICATE_REJECT_MESSAGE


CONFER_WITH_SHANNON = (
    "Shannon will review. You can change or cancel this request, "
    "or leave it for Shannon to sort out with the schedule."
)


def practice_now() -> datetime:
    return datetime.now(PRACTICE_TZ)


def practice_today() -> date:
    return practice_now().date()


def clip_window_to_now(start_date: date, end_date: date) -> tuple[date, date] | None:
    """Rules only care about today forward. Returns None if the whole window is past."""
    today = practice_today()
    if end_date < today:
        return None
    return max(start_date, today), end_date


def day_off_target_entity(
    *,
    start_date: date,
    end_date: date,
    is_full_day: bool = True,
    start_time: time | None = None,
    end_time: time | None = None,
    segments: list[dict] | None = None,
    dayoff_id: int | None = None,
) -> dict:
    return {
        "type": "day_off",
        "start_date": start_date,
        "end_date": end_date,
        "is_full_day": is_full_day,
        "start_time": start_time,
        "end_time": end_time,
        "segments": segments or [],
        "id": dayoff_id,
    }


def target_entity_from_dayoff(dayoff: DayOff) -> dict:
    segments = []
    if dayoff.segments:
        try:
            parsed = json.loads(dayoff.segments)
            if isinstance(parsed, list):
                segments = parsed
        except (TypeError, ValueError, json.JSONDecodeError):
            segments = []
    return day_off_target_entity(
        start_date=dayoff.start_date,
        end_date=dayoff.end_date,
        is_full_day=bool(dayoff.is_full_day if dayoff.is_full_day is not None else True),
        start_time=dayoff.start_time,
        end_time=dayoff.end_time,
        segments=segments,
        dayoff_id=dayoff.id,
    )


def overlapping_day_off(
    db: Session,
    surgeon_id: int,
    start_date: date,
    end_date: date,
    *,
    exclude_id: int | None = None,
    statuses: tuple[str, ...] = ("pending", "approved"),
) -> DayOff | None:
    query = db.query(DayOff).filter(
        DayOff.surgeon_id == surgeon_id,
        DayOff.status.in_(list(statuses)),
        DayOff.start_date <= end_date,
        DayOff.end_date >= start_date,
    )
    if exclude_id is not None:
        query = query.filter(DayOff.id != exclude_id)
    return query.order_by(DayOff.id.asc()).first()


def day_off_overlap_advisory(
    db: Session,
    surgeon_id: int,
    start_date: date,
    end_date: date,
    *,
    exclude_id: int | None = None,
) -> str | None:
    """Advise on overlap with pending/approved time off — never blocks submit."""
    existing = overlapping_day_off(
        db,
        surgeon_id,
        start_date,
        end_date,
        exclude_id=exclude_id,
        statuses=("pending", "approved"),
    )
    if not existing:
        return None
    status = (existing.status or "pending").strip().lower()
    start_label = existing.start_date.strftime("%b %-d")
    end_label = existing.end_date.strftime("%b %-d")
    range_label = start_label if existing.start_date == existing.end_date else f"{start_label}–{end_label}"
    status_label = "approved" if status == "approved" else "pending"
    return (
        f"These dates overlap your {status_label} time off ({range_label}). "
        f"You can cancel or edit that request, or leave both — Shannon will sort it out."
    )


def reject_if_duplicate_day_off(
    db: Session,
    surgeon_id: int,
    start_date: date,
    end_date: date,
    *,
    exclude_id: int | None = None,
    as_http: bool = False,
    statuses: tuple[str, ...] = ("pending", "approved"),
) -> DayOff | None:
    """Compatibility wrapper: finds overlap but never rejects.

    Surgeons may change plans; overlap is advisory only. ``as_http`` is ignored.
    """
    _ = as_http  # never hard-block
    return overlapping_day_off(
        db,
        surgeon_id,
        start_date,
        end_date,
        exclude_id=exclude_id,
        statuses=statuses,
    )


def delete_duplicate_day_off_and_notify(db: Session, duplicate: DayOff, *, keep: DayOff) -> None:
    """Remove a duplicate row and tell the surgeon their original still stands."""
    surgeon_id = duplicate.surgeon_id
    start = duplicate.start_date
    end = duplicate.end_date
    dup_id = duplicate.id
    db.delete(duplicate)
    db.commit()

    date_label = start.strftime("%b %-d")
    if end != start:
        date_label = f"{start.strftime('%b %-d')}–{end.strftime('%b %-d')}"
    title = "Duplicate request removed"
    body = (
        f"Your duplicate time-off request for {date_label} was removed. "
        f"Your original request (#{keep.id}) is still pending Shannon's review."
    )
    send_native_push_to_surgeon(
        surgeon_id,
        title,
        body,
        db,
        {"type": "day_off", "requestId": keep.id, "status": "duplicate_removed"},
    )
    send_push_to_surgeon(
        surgeon_id,
        title,
        body,
        db,
        url="/surgeon/request-off",
        data={"type": "day_off", "requestId": keep.id},
    )
    notify_admins(
        "Duplicate time-off removed",
        f"Removed duplicate day-off #{dup_id}; kept #{keep.id} for {date_label}.",
        db,
        kind="day_off_duplicate",
        payload={"keptId": keep.id, "deletedId": dup_id, "surgeonId": surgeon_id},
        require_dayoff_opt_in=True,
    )


def purge_newer_duplicates_for_request(
    db: Session,
    surgeon_id: int,
    start_date: date,
    end_date: date,
    *,
    keep_id: int,
) -> int:
    """Keep the earliest overlapping *pending* request; delete later pending duplicates.

    Approved rows are never considered — otherwise a new extension request would be
    deleted because an older approved id sorts first.
    """
    rows = (
        db.query(DayOff)
        .filter(
            DayOff.surgeon_id == surgeon_id,
            DayOff.status == "pending",
            DayOff.start_date <= end_date,
            DayOff.end_date >= start_date,
        )
        .order_by(DayOff.id.asc())
        .all()
    )
    if len(rows) <= 1:
        return 0
    keeper = rows[0]
    if keep_id and any(r.id == keep_id for r in rows):
        # Prefer earliest pending (stable anti-dup). keep_id is usually that row.
        pass
    removed = 0
    for row in rows[1:]:
        delete_duplicate_day_off_and_notify(db, row, keep=keeper)
        removed += 1
    return removed


def conflict_to_finding(conflict, *, surgeon_message: str | None = None) -> DayOffFinding:
    kind = (conflict.conflicting_entity_type or conflict.rule_id or "schedule").lower()
    msg = conflict.message
    return DayOffFinding(
        severity=getattr(conflict, "severity", None) or "warning",
        kind=kind,
        date=conflict.date,
        message=msg,
        surgeon_message=surgeon_message or f"{msg}. {CONFER_WITH_SHANNON}",
        clinic_group_id=conflict.conflicting_entity_id if kind == "clinic_group" else None,
    )


def evaluate_day_off_conflicts(
    db: Session,
    surgeon_id: int,
    start_date: date,
    end_date: date,
    *,
    target_entity: dict | None = None,
    exclude_dayoff_id: int | None = None,
) -> list:
    clipped = clip_window_to_now(start_date, end_date)
    if clipped is None:
        return []
    eval_start, eval_end = clipped
    entity = target_entity or day_off_target_entity(start_date=start_date, end_date=end_date)
    entity = dict(entity)
    entity["start_date"] = eval_start
    entity["end_date"] = eval_end
    exclude = ("day_off", exclude_dayoff_id) if exclude_dayoff_id is not None else None
    conflicts = check_conflicts_structured(
        surgeon_id,
        eval_start,
        eval_end,
        db,
        exclude_entity=exclude,
        target_entity=entity,
    )
    today = practice_today()
    now = practice_now().replace(tzinfo=None)
    filtered = []
    for conflict in conflicts:
        if conflict.date < today:
            continue
        if conflict.date == today:
            # Drop conflicts that ended before now (past half-day on today).
            # Full-day / unknown end still count.
            pass
        filtered.append(conflict)
    return filtered


def build_dayoff_review_findings(
    db: Session,
    dayoff: DayOff,
) -> list[DayOffFinding]:
    from .scheduling_guardrails_service import clinic_group_day_off_findings

    surgeon = dayoff.surgeon or db.get(Surgeon, dayoff.surgeon_id)
    findings: list[DayOffFinding] = []
    seen: set[str] = set()

    for finding in clinic_group_day_off_findings(
        db, surgeon, dayoff.start_date, dayoff.end_date, exclude_dayoff_id=dayoff.id
    ):
        key = f"{finding.kind}:{finding.date}:{finding.message}"
        if key not in seen:
            seen.add(key)
            findings.append(finding)

    for conflict in evaluate_day_off_conflicts(
        db,
        dayoff.surgeon_id,
        dayoff.start_date,
        dayoff.end_date,
        target_entity=target_entity_from_dayoff(dayoff),
        exclude_dayoff_id=dayoff.id,
    ):
        # Clinic group already covered above via dedicated findings (nicer copy).
        if conflict.rule_id == "CLINIC_GROUP_DAY_OFF_CAPACITY":
            continue
        finding = conflict_to_finding(conflict)
        key = f"{finding.kind}:{finding.date}:{finding.message}"
        if key not in seen:
            seen.add(key)
            findings.append(finding)
    return findings


def store_full_dayoff_findings(db: Session, dayoff: DayOff) -> list[DayOffFinding]:
    findings = build_dayoff_review_findings(db, dayoff)
    dayoff.review_findings = encode_findings(findings)
    db.commit()
    return findings


def surgeon_friendly_conflict_message(findings: list[DayOffFinding] | list[dict]) -> str:
    parts: list[str] = []
    for finding in findings:
        if isinstance(finding, dict):
            msg = finding.get("surgeonMessage") or finding.get("message")
        else:
            msg = finding.surgeon_message or finding.message
        if msg and msg not in parts:
            parts.append(msg)
    if not parts:
        return ""
    body = " · ".join(parts[:4])
    if CONFER_WITH_SHANNON not in body:
        body = f"{body} {CONFER_WITH_SHANNON}"
    return body


def notify_missing_rule(db: Session, rule_id: str, detail: str) -> None:
    log.error("Missing/failed scheduling rule %s: %s", rule_id, detail)
    try:
        notify_admins(
            "Scheduling rule issue",
            f"Rule {rule_id} failed or is missing a path: {detail}",
            db,
            kind="rules_engine_error",
            payload={"ruleId": rule_id, "detail": detail[:500]},
            require_schedule_opt_in=True,
        )
    except Exception:
        log.exception("Failed to notify admins about missing rule %s", rule_id)


def findings_as_admin_map(findings: list[DayOffFinding] | list[dict]) -> list[dict]:
    return finding_dicts(findings) if findings and hasattr(findings[0], "as_dict") else list(findings or [])
