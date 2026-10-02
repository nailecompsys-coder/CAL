"""Section builders for the native iOS home payload."""
from collections import defaultdict
from datetime import date, timedelta

from sqlalchemy import case, func
from sqlalchemy.orm import Session, joinedload

from .models import CallBackup, CallCoverage, CallRotation, DayOff, NativeScheduleAlert, Surgeon
from .native_support import date_label, serialize_call_assignment, serialize_native_alert
from .surgeon_visibility import surgeon_is_visible


def build_native_call_schedule(
    db: Session,
    viewer: Surgeon,
    start_date: date,
    end_date: date,
    days_by_date: dict[str, dict],
) -> list[dict]:
    rotations = db.query(CallRotation).options(
        joinedload(CallRotation.surgeon),
        joinedload(CallRotation.call_group),
        joinedload(CallRotation.coverages).joinedload(CallCoverage.covering_surgeon),
        joinedload(CallRotation.backup).joinedload(CallBackup.surgeon),
    ).filter(
        CallRotation.date >= start_date,
        CallRotation.date <= end_date,
    ).order_by(CallRotation.date, CallRotation.call_group_id, CallRotation.id).all()

    call_by_date: dict[str, list[dict]] = defaultdict(list)
    for rotation in rotations:
        if rotation.surgeon and not surgeon_is_visible(rotation.surgeon):
            continue
        assignment = serialize_call_assignment(rotation, viewer.id)
        key = rotation.date.isoformat()
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
