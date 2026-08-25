"""In-app Grok look-ahead: CAL finds the gaps, then speaks them in plain English.

No xAI call on this slice. The bot in the portal is the face; the schedule
database is the source of truth.
"""
from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy.orm import Session, joinedload

from .admin_notification_href import admin_notification_href, clinic_schedule_fix_href
from .models import AdminNotification, CallCoverage, CallRotation, Surgeon
from .off_conflict_service import day_off_status_map, detect_off_conflicts
from .scheduling_gate_service import practice_today
from .surgeon_visibility import surgeon_is_visible

LOOKAHEAD_DAYS = 14


def build_grok_lookahead(db: Session, *, today: date | None = None) -> dict:
    start = today or practice_today()
    end = start + timedelta(days=LOOKAHEAD_DAYS - 1)
    cleared = reconcile_stale_call_coverage_notifications(db)
    issues = _call_vs_time_off(db, start, end)
    issues.extend(_block_work_while_off(db, start, end))
    issues.sort(key=lambda row: (row["date"], row.get("kind") or "", row.get("message") or ""))
    trimmed = issues[:40]
    return {
        "from": start.isoformat(),
        "to": end.isoformat(),
        "voice": "cal",
        "briefing": _briefing(len(issues), cleared),
        "issueCount": len(issues),
        "clearedCount": cleared,
        "issues": trimmed,
    }


def reconcile_stale_call_coverage_notifications(
    db: Session,
    admin_user_id: int | None = None,
) -> int:
    """Drop leftover coverage-conflict cards once the clash is gone.

    Grok-BOT owns this: covering while off, or on-call with no cover while off.
    Fixed ⇒ gone from the feed (not left as read).
    """
    q = db.query(AdminNotification).filter(AdminNotification.kind == "call_coverage_conflict")
    if admin_user_id is not None:
        q = q.filter(AdminNotification.admin_user_id == admin_user_id)
    removed = 0
    for row in q.all():
        if call_coverage_conflict_is_open(db, _payload(row)):
            continue
        db.delete(row)
        removed += 1
    if removed:
        db.commit()
    return removed


def call_coverage_conflict_is_open(db: Session, payload: dict) -> bool:
    """True only while this covering (or assigned) doctor still has time off that day."""
    rotation_id = _as_int(payload.get("rotationId"))
    if not rotation_id:
        return False
    rotation = db.get(CallRotation, rotation_id)
    if rotation is None or rotation.date is None:
        return False
    if rotation.date < practice_today():
        return False
    off_map = day_off_status_map(db, rotation.date, rotation.date)
    covering_id = _as_int(payload.get("coveringSurgeonId"))
    active = rotation.active_coverage
    if covering_id:
        if not active or active.covering_surgeon_id != covering_id:
            return False
        return (covering_id, rotation.date) in off_map
    if active:
        return (active.covering_surgeon_id, rotation.date) in off_map
    if rotation.surgeon_id:
        return (rotation.surgeon_id, rotation.date) in off_map
    return False


def _payload(row: AdminNotification) -> dict:
    import json
    try:
        data = json.loads(row.payload or "{}") if row.payload else {}
    except (TypeError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _as_int(value) -> int | None:
    try:
        if value is None or value == "":
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _briefing(count: int, cleared: int = 0) -> str:
    dropped = ""
    if cleared:
        card = "leftover card" if cleared == 1 else "leftover cards"
        dropped = f"I dropped {cleared} {card} that were already fixed. "
    if count <= 0:
        if dropped:
            return dropped + "Nothing else is stuck in the next 14 days."
        return (
            "Next 14 days look clear for call vs time off, and nobody is marked off "
            "with clinic or OR work still on the board."
        )
    noun = "problem" if count == 1 else "problems"
    return (
        dropped
        + f"I found {count} schedule {noun} in the next 14 days. "
        "Call, coverage, and blocks still have to be worked — time off does not cover those. "
        "The doctors involved need to confirm coverage or pick someone else."
    )


def _call_href(rotation: CallRotation) -> str:
    return admin_notification_href(
        "call_coverage_conflict",
        {
            "rotationId": rotation.id,
            "date": rotation.date.isoformat() if rotation.date else None,
            "callGroupId": rotation.call_group_id,
        },
    )


def _status_label(status: str) -> str:
    return "approved time off" if status == "approved" else "a pending time-off request"


def _call_vs_time_off(db: Session, start: date, end: date) -> list[dict]:
    off_map = day_off_status_map(db, start, end)
    rotations = (
        db.query(CallRotation)
        .options(
            joinedload(CallRotation.surgeon),
            joinedload(CallRotation.call_group),
            joinedload(CallRotation.coverages).joinedload(CallCoverage.covering_surgeon),
            joinedload(CallRotation.coverages).joinedload(CallCoverage.original_surgeon),
        )
        .filter(CallRotation.date >= start, CallRotation.date <= end)
        .all()
    )
    issues: list[dict] = []
    for rotation in rotations:
        group = rotation.call_group.name if rotation.call_group else "call"
        day_label = rotation.date.strftime("%b %-d")
        href = _call_href(rotation)
        active = rotation.active_coverage
        if active:
            covering = active.covering_surgeon or db.get(Surgeon, active.covering_surgeon_id)
            if not surgeon_is_visible(covering):
                continue
            off = off_map.get((covering.id, rotation.date))
            if not off:
                continue
            original = rotation.surgeon or active.original_surgeon or db.get(
                Surgeon, active.original_surgeon_id or rotation.surgeon_id
            )
            original_initials = original.initials if original else "the assigned doctor"
            issues.append({
                "kind": "cover_while_off",
                "date": rotation.date.isoformat(),
                "href": href,
                "message": (
                    f"{covering.initials} is covering {group} for {original_initials} on {day_label} "
                    f"and also has {_status_label(off['status'])}."
                ),
            })
            continue
        if not rotation.surgeon_id:
            continue
        assigned = rotation.surgeon or db.get(Surgeon, rotation.surgeon_id)
        if not surgeon_is_visible(assigned):
            continue
        off = off_map.get((assigned.id, rotation.date))
        if not off:
            continue
        issues.append({
            "kind": "on_call_while_off",
            "date": rotation.date.isoformat(),
            "href": href,
            "message": (
                f"{assigned.initials} is on call ({group}) on {day_label} "
                f"with {_status_label(off['status'])} and no cover assigned."
            ),
        })
    return issues


def _block_work_while_off(db: Session, start: date, end: date) -> list[dict]:
    issues: list[dict] = []
    for conflict in detect_off_conflicts(db, start, end):
        issues.append({
            "kind": "off_with_work",
            "date": conflict.day.isoformat(),
            "href": clinic_schedule_fix_href(day=conflict.day, surgeon_id=conflict.surgeon_id),
            "message": (
                f"{conflict.surgeon_initials} has time off on {conflict.day.strftime('%b %-d')} "
                "but still has clinic or OR work that day."
            ),
        })
    return issues
