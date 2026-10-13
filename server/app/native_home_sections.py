"""Section builders for the native iOS home payload."""
from collections import defaultdict
from datetime import date, timedelta

from sqlalchemy import case, func
from sqlalchemy.orm import Session, joinedload

from .models import (
    CallBackup,
    CallCoverage,
    CallDraftAssignment,
    CallRotation,
    DayOff,
    NativeScheduleAlert,
    Surgeon,
)
from .native_call_support import serialize_call_assignment, serialize_draft_call_assignment
from .native_support import date_label, serialize_native_alert
from .surgeon_visibility import surgeon_is_visible


def build_native_call_schedule(
    db: Session,
    viewer: Surgeon,
    start_date: date,
    end_date: date,
    days_by_date: dict[str, dict],
) -> list[dict]:
    """Practice Call for the requested range: live rotations, with Call Builder drafts on top.

    Draft cells are what CJ has built but not Published yet. Calendar must show them
    for any month in range — including years ahead — not only near-term live rows.
    """
    rotations = db.query(CallRotation).options(
        joinedload(CallRotation.surgeon),
        joinedload(CallRotation.call_group),
        joinedload(CallRotation.coverages).joinedload(CallCoverage.covering_surgeon),
        joinedload(CallRotation.backup).joinedload(CallBackup.surgeon),
    ).filter(
        CallRotation.date >= start_date,
        CallRotation.date <= end_date,
    ).order_by(CallRotation.date, CallRotation.call_group_id, CallRotation.id).all()

    drafts = db.query(CallDraftAssignment).options(
        joinedload(CallDraftAssignment.surgeon),
        joinedload(CallDraftAssignment.call_group),
    ).filter(
        CallDraftAssignment.date >= start_date,
        CallDraftAssignment.date <= end_date,
    ).order_by(CallDraftAssignment.date, CallDraftAssignment.call_group_id).all()

    live_by_cell: dict[tuple[date, int | None], CallRotation] = {}
    for rotation in rotations:
        live_by_cell[(rotation.date, rotation.call_group_id)] = rotation

    draft_by_cell: dict[tuple[date, int], CallDraftAssignment] = {
        (row.date, row.call_group_id): row for row in drafts
    }

    cell_keys = sorted(
        set(live_by_cell.keys()) | {(day, group_id) for day, group_id in draft_by_cell},
        key=lambda item: (item[0], item[1] is None, item[1] or 0),
    )

    call_by_date: dict[str, list[dict]] = defaultdict(list)
    for day, group_id in cell_keys:
        draft = draft_by_cell.get((day, group_id)) if group_id is not None else None
        if draft is not None:
            if draft.surgeon and not surgeon_is_visible(draft.surgeon):
                continue
            assignment = serialize_draft_call_assignment(draft, viewer.id)
        else:
            rotation = live_by_cell[(day, group_id)]
            if rotation.surgeon and not surgeon_is_visible(rotation.surgeon):
                continue
            assignment = serialize_call_assignment(rotation, viewer.id)
        key = day.isoformat()
        call_by_date[key].append(assignment)
        if key in days_by_date:
            days_by_date[key]["callAssignments"].append(assignment)

    append_native_off_surgeons(db, viewer, start_date, end_date, days_by_date)
    return [
        {**date_label(start_date + timedelta(days=i)), "assignments": call_by_date.get((start_date + timedelta(days=i)).isoformat(), [])}
        for i in range((end_date - start_date).days + 1)
    ]


def append_native_off_surgeons(
    db: Session,
    viewer: Surgeon,
    start_date: date,
    end_date: date,
    days_by_date: dict[str, dict],
) -> None:
    off_rows = db.query(DayOff).join(Surgeon, Surgeon.id == DayOff.surgeon_id).options(joinedload(DayOff.surgeon)).filter(
        DayOff.status.in_(["pending", "approved"]),
        func.lower(func.trim(func.coalesce(DayOff.reason, ""))) != "no call",
        Surgeon.is_active == True,  # noqa: E712
        func.lower(func.coalesce(Surgeon.email, "")) != "don@clermontitstore.com",
        ~((Surgeon.first_name.ilike("developer")) & (Surgeon.last_name.ilike("admin"))),
        DayOff.start_date <= end_date,
        DayOff.end_date >= start_date,
    ).order_by(
        case((func.coalesce(Surgeon.staff_type, "physician") == "physician", 0), else_=1),
        case((Surgeon.sort_order > 0, Surgeon.sort_order), else_=999999),
        Surgeon.last_name, Surgeon.first_name, DayOff.id,
    ).all()
    for off in off_rows:
        if not surgeon_is_visible(off.surgeon):
            continue
        span = max(off.start_date, start_date)
        span_end = min(off.end_date, end_date)
        while span <= span_end:
            key = span.isoformat()
            if key in days_by_date:
                bucket = "offSurgeons" if off.status == "approved" else "requestedOffSurgeons"
                days_by_date[key][bucket].append({
                    "initials": off.surgeon.initials,
                    "displayName": off.surgeon.full_name,
                    "isSelf": off.surgeon_id == viewer.id,
                    "sortOrder": off.surgeon.sort_order or 0,
                    "staffType": off.surgeon.staff_type or "",
                })
            span += timedelta(days=1)

def native_alerts(db: Session, surgeon: Surgeon) -> dict:
    unread_alert_count = db.query(NativeScheduleAlert).filter(
        NativeScheduleAlert.surgeon_id == surgeon.id,
        NativeScheduleAlert.read_at.is_(None),
    ).count()
    recent_alerts = db.query(NativeScheduleAlert).filter(
        NativeScheduleAlert.surgeon_id == surgeon.id,
    ).order_by(NativeScheduleAlert.created_at.desc(), NativeScheduleAlert.id.desc()).limit(20).all()
    return {
        "unreadCount": unread_alert_count,
        "recent": [serialize_native_alert(row) for row in recent_alerts],
    }
