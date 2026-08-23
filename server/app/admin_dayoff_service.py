"""Services for admin day-off management."""

import calendar as calendar_lib
from collections import defaultdict
from datetime import date

from sqlalchemy.orm import Session

from .models import DayOff, Surgeon
from .or_block_service import log_schedule_change
from .push import clear_dayoff_request_notifications, send_push_to_surgeon
from .scheduling_gate_service import day_off_overlap_advisory
from .scheduling_guardrails_service import (
    decode_findings,
    finding_dicts,
    store_dayoff_findings,
)
from .time_off_email_service import send_time_off_decision_email


def resolved_months(resolved: list[DayOff]) -> list[dict]:
    month_map: dict = defaultdict(list)
    for dayoff in resolved:
        month_map[(dayoff.start_date.year, dayoff.start_date.month)].append(dayoff)
    return [
        {"label": f"{calendar_lib.month_name[month].upper()} {year}", "records": records}
        for (year, month), records in sorted(month_map.items())
    ]


def month_window(month_offset: int) -> dict:
    """Calendar month for the Who's Out Gantt (offset from current month)."""
    today = date.today()
    total_months = today.year * 12 + (today.month - 1) + month_offset
    year = total_months // 12
    month = total_months % 12 + 1
    first_day = date(year, month, 1)
    days_in_month = calendar_lib.monthrange(year, month)[1]
    last_day = date(year, month, days_in_month)
    return {
        "today": today,
        "month_offset": month_offset,
        "month_label": first_day.strftime("%B %Y"),
        "month_start": first_day,
        "month_end": last_day,
        "days_in_month": days_in_month,
        "day_numbers": list(range(1, days_in_month + 1)),
    }


def _bar_for_month(dayoff: DayOff, month_start: date, month_end: date, days_in_month: int) -> dict | None:
    start = max(dayoff.start_date, month_start)
    end = min(dayoff.end_date, month_end)
    if start > end:
        return None
    col0 = start.day - 1
    span = (end - start).days + 1
    return {
        "id": dayoff.id,
        "status": dayoff.status or "approved",
        "reason": dayoff.reason or "",
        "notes": dayoff.notes or "",
        "startIso": dayoff.start_date.isoformat(),
        "endIso": dayoff.end_date.isoformat(),
        "labelStart": start.strftime("%-d"),
        "labelEnd": end.strftime("%-d"),
        "leftPct": round(col0 / days_in_month * 100, 4),
        "widthPct": round(span / days_in_month * 100, 4),
        "spanDays": span,
        "clipStart": start,
        "clipEnd": end,
    }


def _assign_lanes(bars: list[dict]) -> tuple[list[dict], int]:
    """Stack overlapping bars into lanes (0-based). Returns (bars_with_lane, lane_count)."""
    if not bars:
        return [], 0
    lane_ends: list[date] = []
    for bar in bars:
        placed = False
        for idx, lane_end in enumerate(lane_ends):
            if bar["clipStart"] > lane_end:
                lane_ends[idx] = bar["clipEnd"]
                bar["lane"] = idx
                placed = True
                break
        if not placed:
            bar["lane"] = len(lane_ends)
            lane_ends.append(bar["clipEnd"])
    return bars, len(lane_ends)


def gantt_rows(
    surgeons: list[Surgeon],
    dayoffs: list[DayOff],
    *,
    month_start: date,
    month_end: date,
    days_in_month: int,
) -> list[dict]:
    """One row per surgeon with Gantt bars clipped to the visible month."""
    by_surgeon: dict[int, list[DayOff]] = defaultdict(list)
    for row in dayoffs:
        if row.status == "denied":
            continue
        if row.end_date < month_start or row.start_date > month_end:
            continue
        by_surgeon[row.surgeon_id].append(row)

    rows = []
    for surgeon in surgeons:
        bars = []
        for dayoff in sorted(by_surgeon.get(surgeon.id, []), key=lambda d: (d.start_date, d.id or 0)):
            bar = _bar_for_month(dayoff, month_start, month_end, days_in_month)
            if bar:
                bars.append(bar)
        bars, lane_count = _assign_lanes(bars)
        for bar in bars:
            bar.pop("clipStart", None)
            bar.pop("clipEnd", None)
        rows.append({
            "surgeon": surgeon,
            "bars": bars,
            "hasBars": bool(bars),
            "laneCount": max(1, lane_count) if bars else 1,
        })
    # Keep People / practice-rank order exactly (seniority). Never bump "who's off" to the top.
    return rows


def dayoff_is_current_or_future(dayoff: DayOff, today: date | None = None) -> bool:
    today = today or date.today()
    return bool(dayoff.end_date and dayoff.end_date >= today)


def pending_conflict_map(db: Session, pending: list[DayOff]) -> dict[int, list[dict]]:
    """Full schedule findings for pending cards (not just clinic-group + raw call)."""
    from .scheduling_gate_service import build_dayoff_review_findings
    from .scheduling_guardrails_service import finding_dicts

    conflict_map = {}
    for dayoff in pending:
        stored = decode_findings(dayoff.review_findings)
        if stored:
            conflict_map[dayoff.id] = stored
            continue
        conflict_map[dayoff.id] = finding_dicts(build_dayoff_review_findings(db, dayoff))
    return conflict_map


def conflict_messages_for_dayoff(db: Session, dayoff: DayOff) -> list[str]:
    from .scheduling_gate_service import evaluate_day_off_conflicts, target_entity_from_dayoff

    conflicts = evaluate_day_off_conflicts(
        db,
        dayoff.surgeon_id,
        dayoff.start_date,
        dayoff.end_date,
        target_entity=target_entity_from_dayoff(dayoff),
        exclude_dayoff_id=dayoff.id,
    )
    surgeon = db.get(Surgeon, dayoff.surgeon_id)
    if surgeon and conflicts:
        return [f"{surgeon.full_name}: {c.message}" for c in conflicts]
    return [c.message for c in conflicts]


def add_approved_dayoff(
    db: Session,
    surgeon_id: int,
    start: date,
    end: date,
    reason: str,
    notes: str,
    approved_by: int,
) -> list[str]:
    advisories: list[str] = []
    overlap_note = day_off_overlap_advisory(db, surgeon_id, start, end)
    if overlap_note:
        advisories.append(overlap_note)

    dayoff = DayOff(
        surgeon_id=surgeon_id,
        start_date=start,
        end_date=end,
        reason=reason,
        notes=notes or None,
        status="approved",
        approved_by=approved_by,
    )
    db.add(dayoff)
    db.commit()
    db.refresh(dayoff)
    surgeon = db.get(Surgeon, surgeon_id)
    log_schedule_change(
        db,
        event_type="day_off_approved",
        surgeon_id=surgeon_id,
        admin_user_id=approved_by,
        event_date=start,
        title="Time off approved",
        body=f"{surgeon.initials if surgeon else ''}: {start.strftime('%b %-d')} to {end.strftime('%b %-d')}",
    )
    db.commit()
    findings = store_dayoff_findings(db, dayoff)
    send_push_to_surgeon(
        surgeon_id,
        "Day Off Added",
        f"Admin added approved time off: {start.strftime('%b %d')}–{end.strftime('%b %d')}.",
        db,
    )
    if surgeon:
        send_time_off_decision_email(surgeon, dayoff, decision="approved")
    return advisories + [f["message"] for f in finding_dicts(findings)] + conflict_messages_for_dayoff(db, dayoff)


def approve_dayoff(db: Session, dayoff_id: int, approved_by: int) -> list[str] | None:
    dayoff = db.get(DayOff, dayoff_id)
    if not dayoff:
        return None
    dayoff.status = "approved"
    dayoff.approved_by = approved_by
    surgeon = db.get(Surgeon, dayoff.surgeon_id)
    log_schedule_change(
        db,
        event_type="day_off_approved",
        surgeon_id=dayoff.surgeon_id,
        admin_user_id=approved_by,
        event_date=dayoff.start_date,
        title="Time off approved",
        body=f"{surgeon.initials if surgeon else ''}: {dayoff.start_date.strftime('%b %-d')} to {dayoff.end_date.strftime('%b %-d')}",
    )
    store_dayoff_findings(db, dayoff)
    # store_dayoff_findings commits; ensure status is persisted even if findings were a no-op path.
    db.commit()
    clear_dayoff_request_notifications(db, dayoff_id)
    send_push_to_surgeon(
        dayoff.surgeon_id,
        "Days Off Approved",
        f"Your request for {dayoff.start_date.strftime('%b %d')}–{dayoff.end_date.strftime('%b %d')} was approved.",
        db,
    )
    if surgeon:
        send_time_off_decision_email(surgeon, dayoff, decision="approved")
    return conflict_messages_for_dayoff(db, dayoff)


def bulk_approve_dayoffs(db: Session, ids: list[int], approved_by: int) -> int:
    approved = 0
    for dayoff_id in ids:
        conflicts = approve_dayoff(db, dayoff_id, approved_by)
        if conflicts is not None:
            approved += 1
    return approved


def deny_dayoff(db: Session, dayoff_id: int, admin_note: str, approved_by: int) -> None:
    dayoff = db.get(DayOff, dayoff_id)
    if dayoff:
        dayoff.status = "denied"
        dayoff.admin_note = admin_note or None
        dayoff.approved_by = approved_by
        surgeon = db.get(Surgeon, dayoff.surgeon_id)
        log_schedule_change(
            db,
            event_type="day_off_denied",
            surgeon_id=dayoff.surgeon_id,
            admin_user_id=approved_by,
            event_date=dayoff.start_date,
            title="Time off denied",
            body=f"{surgeon.initials if surgeon else ''}: {dayoff.start_date.strftime('%b %-d')} to {dayoff.end_date.strftime('%b %-d')}",
        )
        db.commit()
        clear_dayoff_request_notifications(db, dayoff_id)
        msg = admin_note if admin_note else f"Your request for {dayoff.start_date.strftime('%b %d')}–{dayoff.end_date.strftime('%b %d')} was not approved."
        send_push_to_surgeon(dayoff.surgeon_id, "Days Off Request", msg, db)
        if surgeon:
            send_time_off_decision_email(surgeon, dayoff, decision="denied")


def edit_dayoff(db: Session, dayoff_id: int, start: date, end: date, reason: str, notes: str) -> None:
    dayoff = db.get(DayOff, dayoff_id)
    if dayoff:
        dayoff.start_date = start
        dayoff.end_date = end
        dayoff.reason = reason
        dayoff.notes = notes
        surgeon = db.get(Surgeon, dayoff.surgeon_id)
        log_schedule_change(
            db,
            event_type="day_off_updated",
            surgeon_id=dayoff.surgeon_id,
            event_date=start,
            title="Time off updated",
            body=f"{surgeon.initials if surgeon else ''}: {start.strftime('%b %-d')} to {end.strftime('%b %-d')}",
        )
        store_dayoff_findings(db, dayoff)
        db.commit()


def delete_dayoff(db: Session, dayoff_id: int) -> bool:
    dayoff = db.get(DayOff, dayoff_id)
    if not dayoff:
        return False
    db.delete(dayoff)
    db.commit()
    return True
