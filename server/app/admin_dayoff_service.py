"""Services for admin day-off management."""

import calendar as calendar_lib
from collections import defaultdict
from datetime import date

from sqlalchemy.orm import Session

from .conflicts import check_conflicts
from .models import CallRotation, DayOff, Surgeon
from .push import send_push_to_surgeon
from .scheduling_guardrails_service import (
    decode_findings,
    finding_dicts,
    store_dayoff_findings,
)


def resolved_months(resolved: list[DayOff]) -> list[dict]:
    month_map: dict = defaultdict(list)
    for dayoff in resolved:
        month_map[(dayoff.start_date.year, dayoff.start_date.month)].append(dayoff)
    return [
        {"label": f"{calendar_lib.month_name[month].upper()} {year}", "records": records}
        for (year, month), records in sorted(month_map.items())
    ]


def dayoff_is_current_or_future(dayoff: DayOff, today: date | None = None) -> bool:
    today = today or date.today()
    return bool(dayoff.end_date and dayoff.end_date >= today)


def pending_conflict_map(db: Session, pending: list[DayOff]) -> dict[int, list[dict]]:
    conflict_map = {}
    for dayoff in pending:
        findings = decode_findings(dayoff.review_findings)
        call_rows = db.query(CallRotation).filter(
            CallRotation.surgeon_id == dayoff.surgeon_id,
            CallRotation.date >= dayoff.start_date,
            CallRotation.date <= dayoff.end_date,
        ).all()
        for row in call_rows:
            findings.append({
                "severity": "warning",
                "kind": "call_assignment",
                "date": row.date.isoformat(),
                "message": f"On-call assignment on {row.date.strftime('%b %-d')}",
            })
        conflict_map[dayoff.id] = findings
    return conflict_map


def conflict_messages_for_dayoff(db: Session, dayoff: DayOff) -> list[str]:
    conflicts = check_conflicts(
        dayoff.surgeon_id,
        dayoff.start_date,
        dayoff.end_date,
        db,
        exclude_dayoff_id=dayoff.id,
        target_entity={"type": "day_off", "start_date": dayoff.start_date, "end_date": dayoff.end_date},
    )
    surgeon = db.get(Surgeon, dayoff.surgeon_id)
    if surgeon and conflicts:
        return [f"{surgeon.full_name}: " + conflict for conflict in conflicts]
    return conflicts


def add_approved_dayoff(
    db: Session,
    surgeon_id: int,
    start: date,
    end: date,
    reason: str,
    notes: str,
    approved_by: int,
) -> list[str]:
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
    findings = store_dayoff_findings(db, dayoff)
    send_push_to_surgeon(
        surgeon_id,
        "Day Off Added",
        f"Admin added approved time off: {start.strftime('%b %d')}–{end.strftime('%b %d')}.",
        db,
    )
    return [f["message"] for f in finding_dicts(findings)] + conflict_messages_for_dayoff(db, dayoff)


def approve_dayoff(db: Session, dayoff_id: int, approved_by: int) -> list[str] | None:
    dayoff = db.get(DayOff, dayoff_id)
    if not dayoff:
        return None
    dayoff.status = "approved"
    dayoff.approved_by = approved_by
    store_dayoff_findings(db, dayoff)
    send_push_to_surgeon(
        dayoff.surgeon_id,
        "Days Off Approved",
        f"Your request for {dayoff.start_date.strftime('%b %d')}–{dayoff.end_date.strftime('%b %d')} was approved.",
        db,
    )
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
        db.commit()
        msg = admin_note if admin_note else f"Your request for {dayoff.start_date.strftime('%b %d')}–{dayoff.end_date.strftime('%b %d')} was not approved."
        send_push_to_surgeon(dayoff.surgeon_id, "Days Off Request", msg, db)


def edit_dayoff(db: Session, dayoff_id: int, start: date, end: date, reason: str, notes: str) -> None:
    dayoff = db.get(DayOff, dayoff_id)
    if dayoff:
        dayoff.start_date = start
        dayoff.end_date = end
        dayoff.reason = reason
        dayoff.notes = notes
        store_dayoff_findings(db, dayoff)
        db.commit()


def delete_dayoff(db: Session, dayoff_id: int) -> bool:
    dayoff = db.get(DayOff, dayoff_id)
    if not dayoff:
        return False
    db.delete(dayoff)
    db.commit()
    return True
