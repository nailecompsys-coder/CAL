"""Services for admin meeting management."""

from __future__ import annotations

import calendar as calendar_lib
from datetime import date, datetime, timedelta
from datetime import time as dtime

from sqlalchemy.orm import Session

from .conflicts import check_conflicts
from .models import Meeting, MeetingAttendee, Surgeon
from .or_block_service import log_schedule_change
from .push import notify_schedule_change
from .surgeon_visibility import surgeon_is_visible


def month_schedule_days(month_offset: int) -> dict:
    today = date.today()
    total_months = today.year * 12 + (today.month - 1) + month_offset
    year = total_months // 12
    month = total_months % 12 + 1
    first_day = date(year, month, 1)
    days_in_month = calendar_lib.monthrange(year, month)[1]
    schedule_days = [date(year, month, day) for day in range(1, days_in_month + 1)]
    return {
        "today": today,
        "schedule_days": schedule_days,
        "month_label": first_day.strftime("%B %Y"),
        "month_start": first_day,
        "month_end": date(year, month, days_in_month),
        "pad_start": (first_day.weekday() + 1) % 7,
    }


def _parse_meeting_date(value) -> date | None:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    text = (value or "").strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def calendar_events_by_day(
    *,
    schedule_days: list[date],
    cal_meetings: list[Meeting],
    aprima_meetings: list[dict],
) -> dict[date, list[dict]]:
    """Compact day-cell payloads for the Meetings month grid."""
    by_day: dict[date, list[dict]] = {day: [] for day in schedule_days}
    for meeting in cal_meetings:
        day = meeting.date
        if day not in by_day:
            continue
        attendees = []
        for row in meeting.attendees or []:
            surgeon = row.surgeon
            if surgeon and surgeon_is_visible(surgeon):
                attendees.append(surgeon.initials or surgeon.last_name or "?")
        by_day[day].append({
            "source": "cal",
            "id": meeting.id,
            "title": meeting.title or "Meeting",
            "start": meeting.start_time.strftime("%H:%M") if meeting.start_time else "",
            "end": meeting.end_time.strftime("%H:%M") if meeting.end_time else "",
            "startLabel": meeting.start_time.strftime("%-I:%M%p").lower().replace(":00", "") if meeting.start_time else "",
            "location": meeting.location_text or "",
            "notes": meeting.notes or "",
            "recurrence": meeting.recurrence_rule or "",
            "attendees": attendees,
            "attendeeIds": [row.surgeon_id for row in (meeting.attendees or [])],
            "dateIso": day.isoformat(),
        })
    for row in aprima_meetings:
        day = _parse_meeting_date(row.get("date"))
        if day is None or day not in by_day:
            continue
        start = (row.get("start") or "").strip()
        end = (row.get("end") or "").strip()
        start_label = ""
        if start:
            try:
                parsed = dtime.fromisoformat(start)
                start_label = parsed.strftime("%-I:%M%p").lower().replace(":00", "")
            except ValueError:
                start_label = start
        by_day[day].append({
            "source": "aprima",
            "id": row.get("id") or "",
            "title": row.get("title") or "Meeting",
            "start": start,
            "end": end,
            "startLabel": start_label,
            "location": row.get("serviceSite") or row.get("room") or "",
            "notes": row.get("reason") or "",
            "recurrence": "",
            "attendees": [row["surgeonInitials"]] if row.get("surgeonInitials") else (
                [row["surgeonName"]] if row.get("surgeonName") else []
            ),
            "attendeeIds": [],
            "dateIso": day.isoformat(),
            "surgeonName": row.get("surgeonName") or "",
            "room": row.get("room") or "",
        })
    for day, events in by_day.items():
        events.sort(key=lambda item: (item.get("start") or "99:99", item.get("title") or ""))
    # ISO keys so templates/JSON round-trip cleanly
    return {day.isoformat(): events for day, events in by_day.items()}


def parse_meeting_fields(
    title: str,
    meeting_date: str,
    start_time: str,
    end_time: str,
    location_text: str,
    recurrence_rule: str,
    notes: str,
) -> dict:
    return {
        "title": title.strip(),
        "date": date.fromisoformat(meeting_date),
        "start_time": dtime.fromisoformat(start_time) if start_time else None,
        "end_time": dtime.fromisoformat(end_time) if end_time else None,
        "location_text": location_text.strip(),
        "recurrence_rule": recurrence_rule if recurrence_rule != "none" else None,
        "notes": notes.strip(),
    }


def sync_meeting_attendees(db: Session, meeting: Meeting, attendee_ids: list[int]) -> None:
    normalized_ids = []
    seen = set()
    for surgeon_id in attendee_ids:
        if surgeon_id in seen:
            continue
        seen.add(surgeon_id)
        normalized_ids.append(surgeon_id)

    existing_by_surgeon = {row.surgeon_id: row for row in meeting.attendees}
    target_ids = set(normalized_ids)

    for surgeon_id, attendee in list(existing_by_surgeon.items()):
        if surgeon_id not in target_ids:
            db.delete(attendee)

    for surgeon_id in normalized_ids:
        if surgeon_id not in existing_by_surgeon:
            db.add(MeetingAttendee(meeting_id=meeting.id, surgeon_id=surgeon_id))


def target_surgeon_ids(db: Session, attendee_ids: list[int]) -> list[int]:
    if attendee_ids:
        return list(dict.fromkeys(attendee_ids))
    return [
        row.id
        for row in db.query(Surgeon)
        .filter(Surgeon.is_active == True)  # noqa: E712
        .order_by(Surgeon.last_name, Surgeon.first_name, Surgeon.id)
        .all()
        if surgeon_is_visible(row)
    ]


def notify_and_check_meeting_conflicts(
    db: Session,
    meeting: Meeting,
    fields: dict,
    attendee_ids: list[int],
    message_action: str,
    message_time: str,
) -> list[str]:
    conflicts = []
    for surgeon_id in target_surgeon_ids(db, attendee_ids):
        notify_schedule_change(
            [surgeon_id],
            "Schedule updated",
            f"Meeting {message_action} {fields['date'].strftime('%a')} {message_time or 'TBD'}: {fields['title']}",
            db,
            payload={"type": "meeting", "meetingId": meeting.id},
        )
        log_schedule_change(
            db,
            event_type="meeting_changed",
            surgeon_id=surgeon_id,
            event_date=fields["date"],
            title="Meeting changed",
            body=f"{message_action.title()}: {fields['title']} {message_time or 'TBD'}",
        )
        surgeon = db.get(Surgeon, surgeon_id)
        raw = check_conflicts(
            surgeon_id,
            fields["date"],
            fields["date"],
            db,
            exclude_meeting_id=meeting.id,
            target_entity={
                "type": "meeting",
                "date": fields["date"],
                "start_time": fields["start_time"],
                "end_time": fields["end_time"],
            },
        )
        if surgeon and raw:
            conflicts += [f"{surgeon.full_name}: " + conflict for conflict in raw]
    db.commit()
    return conflicts


def create_meeting(
    db: Session,
    admin_id: int,
    fields: dict,
    attendee_ids: list[int],
    message_time: str,
) -> list[str]:
    meeting = Meeting(
        title=fields["title"],
        date=fields["date"],
        start_time=fields["start_time"],
        end_time=fields["end_time"],
        location_text=fields["location_text"],
        recurrence_rule=fields["recurrence_rule"],
        notes=fields["notes"],
        created_by=admin_id,
    )
    db.add(meeting)
    db.flush()
    sync_meeting_attendees(db, meeting, attendee_ids)
    db.commit()
    return notify_and_check_meeting_conflicts(db, meeting, fields, attendee_ids, "added", message_time)


def update_meeting(
    db: Session,
    meeting: Meeting,
    fields: dict,
    attendee_ids: list[int],
    message_time: str,
) -> list[str]:
    meeting.title = fields["title"]
    meeting.date = fields["date"]
    meeting.start_time = fields["start_time"]
    meeting.end_time = fields["end_time"]
    meeting.location_text = fields["location_text"]
    meeting.recurrence_rule = fields["recurrence_rule"]
    meeting.notes = fields["notes"]
    sync_meeting_attendees(db, meeting, attendee_ids)
    db.commit()
    return notify_and_check_meeting_conflicts(db, meeting, fields, attendee_ids, "updated", message_time)


def delete_meeting(db: Session, meeting: Meeting) -> None:
    attendee_ids = [row.surgeon_id for row in meeting.attendees]
    surgeon_ids = target_surgeon_ids(db, attendee_ids)
    meeting_id = meeting.id
    meeting_date = meeting.date
    meeting_title = meeting.title
    db.delete(meeting)
    db.commit()
    for surgeon_id in surgeon_ids:
        log_schedule_change(
            db,
            event_type="meeting_removed",
            surgeon_id=surgeon_id,
            event_date=meeting_date,
            title="Meeting removed",
            body=meeting_title,
        )
        db.commit()
        notify_schedule_change(
            [surgeon_id],
            "Schedule updated",
            f"Meeting removed {meeting_date.strftime('%a')}: {meeting_title}",
            db,
            payload={"type": "meeting", "meetingId": meeting_id},
        )
