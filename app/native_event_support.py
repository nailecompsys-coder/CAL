"""Native meeting and alert helpers."""

import json
from datetime import date

from sqlalchemy import or_
from sqlalchemy.orm import Session

from .models import Meeting, MeetingAttendee, NativeScheduleAlert


def serialize_native_alert(row: NativeScheduleAlert) -> dict:
    try:
        payload = json.loads(row.payload or "{}")
    except json.JSONDecodeError:
        payload = {}
    return {
        "id": row.id,
        "title": row.title,
        "body": row.body,
        "kind": row.kind or "schedule",
        "payload": payload,
        "isRead": row.read_at is not None,
        "createdAt": row.created_at.isoformat() if row.created_at else "",
    }


def meetings_for_surgeon(db: Session, surgeon_id: int, start_date: date, end_date: date) -> list[Meeting]:
    return (
        db.query(Meeting)
        .outerjoin(MeetingAttendee)
        .filter(
            Meeting.date >= start_date,
            Meeting.date <= end_date,
            or_(
                MeetingAttendee.surgeon_id == surgeon_id,
                ~Meeting.attendees.any(),
            ),
        )
        .distinct()
        .order_by(Meeting.date, Meeting.start_time, Meeting.id)
        .all()
    )
