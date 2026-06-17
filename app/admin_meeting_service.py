"""Services for admin meeting management."""

from datetime import date
from datetime import time as dtime

from sqlalchemy.orm import Session

from .conflicts import check_conflicts
from .models import Meeting, MeetingAttendee, Surgeon
from .push import send_push_to_surgeon
from .surgeon_visibility import surgeon_is_visible


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
        send_push_to_surgeon(
            surgeon_id,
            "Schedule updated",
            f"Meeting {message_action} {fields['date'].strftime('%a')} {message_time or 'TBD'}: {fields['title']}",
            db,
            url="/surgeon/schedule",
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
    meeting_date = meeting.date
    meeting_title = meeting.title
    db.delete(meeting)
    db.commit()
    for surgeon_id in surgeon_ids:
        send_push_to_surgeon(
            surgeon_id,
            "Schedule updated",
            f"Meeting removed {meeting_date.strftime('%a')}: {meeting_title}",
            db,
            url="/surgeon/schedule",
        )
