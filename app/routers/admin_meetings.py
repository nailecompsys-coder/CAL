"""Admin portal meeting management routes."""

from datetime import date

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from ..auth import get_current_admin
from ..conflicts import check_conflicts
from ..database import get_db
from ..jinja_env import templates
from ..models import Meeting, MeetingAttendee, Surgeon
from ..push import send_push_to_surgeon
from .admin import _base, _sort_surgeons_physicians_first, _warn_redirect

router = APIRouter(prefix="/admin")


def _parse_meeting_fields(
    title: str,
    meeting_date: str,
    start_time: str,
    end_time: str,
    location_text: str,
    recurrence_rule: str,
    notes: str,
) -> dict:
    from datetime import time as dtime

    return {
        "title": title.strip(),
        "date": date.fromisoformat(meeting_date),
        "start_time": dtime.fromisoformat(start_time) if start_time else None,
        "end_time": dtime.fromisoformat(end_time) if end_time else None,
        "location_text": location_text.strip(),
        "recurrence_rule": recurrence_rule if recurrence_rule != "none" else None,
        "notes": notes.strip(),
    }


def _sync_meeting_attendees(db: Session, meeting: Meeting, attendee_ids: list[int]) -> None:
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


def _target_surgeon_ids(db: Session, attendee_ids: list[int]) -> list[int]:
    if attendee_ids:
        return list(dict.fromkeys(attendee_ids))
    return [
        row.id
        for row in db.query(Surgeon.id)
        .filter(Surgeon.is_active == True)  # noqa: E712
        .order_by(Surgeon.last_name, Surgeon.first_name, Surgeon.id)
        .all()
    ]


@router.get("/meetings", response_class=HTMLResponse)
def meetings_page(request: Request, db: Session = Depends(get_db), admin=Depends(get_current_admin)):
    today = date.today()
    meetings = db.query(Meeting).filter(Meeting.date >= today).order_by(Meeting.date, Meeting.start_time).all()
    surgeons = db.query(Surgeon).filter(Surgeon.is_active == True).order_by(Surgeon.last_name).all()
    surgeons = _sort_surgeons_physicians_first(surgeons)
    return templates.TemplateResponse("admin/meetings.html", _base(
        request, admin, db=db, meetings=meetings, surgeons=surgeons
    ))


@router.post("/meetings/add")
def add_meeting(
    title: str = Form(...),
    meeting_date: str = Form(...),
    start_time: str = Form(""),
    end_time: str = Form(""),
    location_text: str = Form(""),
    recurrence_rule: str = Form("none"),
    notes: str = Form(""),
    attendee_ids: list[int] = Form(default=[]),
    db: Session = Depends(get_db),
    admin=Depends(get_current_admin),
):
    fields = _parse_meeting_fields(
        title=title,
        meeting_date=meeting_date,
        start_time=start_time,
        end_time=end_time,
        location_text=location_text,
        recurrence_rule=recurrence_rule,
        notes=notes,
    )

    meeting = Meeting(
        title=fields["title"],
        date=fields["date"],
        start_time=fields["start_time"],
        end_time=fields["end_time"],
        location_text=fields["location_text"],
        recurrence_rule=fields["recurrence_rule"],
        notes=fields["notes"],
        created_by=admin.id,
    )
    db.add(meeting)
    db.flush()

    _sync_meeting_attendees(db, meeting, attendee_ids)

    db.commit()

    target_surgeon_ids = _target_surgeon_ids(db, attendee_ids)
    all_conflicts = []
    for surgeon_id in target_surgeon_ids:
        send_push_to_surgeon(
            surgeon_id,
            "Schedule updated",
            f"Meeting added {fields['date'].strftime('%a')} {start_time or 'TBD'}: {fields['title']}",
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
            all_conflicts += [f"{surgeon.full_name}: " + conflict for conflict in raw]

    return _warn_redirect("/admin/meetings", all_conflicts)


@router.post("/meetings/{meeting_id}/edit")
def edit_meeting(
    meeting_id: int,
    title: str = Form(...),
    meeting_date: str = Form(...),
    start_time: str = Form(""),
    end_time: str = Form(""),
    location_text: str = Form(""),
    recurrence_rule: str = Form("none"),
    notes: str = Form(""),
    attendee_ids: list[int] = Form(default=[]),
    db: Session = Depends(get_db),
    admin=Depends(get_current_admin),
):
    meeting = db.get(Meeting, meeting_id)
    if not meeting:
        return RedirectResponse("/admin/meetings?msg=not_found", status_code=303)

    fields = _parse_meeting_fields(
        title=title,
        meeting_date=meeting_date,
        start_time=start_time,
        end_time=end_time,
        location_text=location_text,
        recurrence_rule=recurrence_rule,
        notes=notes,
    )

    meeting.title = fields["title"]
    meeting.date = fields["date"]
    meeting.start_time = fields["start_time"]
    meeting.end_time = fields["end_time"]
    meeting.location_text = fields["location_text"]
    meeting.recurrence_rule = fields["recurrence_rule"]
    meeting.notes = fields["notes"]

    _sync_meeting_attendees(db, meeting, attendee_ids)
    db.commit()

    target_surgeon_ids = _target_surgeon_ids(db, attendee_ids)
    all_conflicts = []
    for surgeon_id in target_surgeon_ids:
        send_push_to_surgeon(
            surgeon_id,
            "Schedule updated",
            f"Meeting updated {fields['date'].strftime('%a')} {start_time or 'TBD'}: {fields['title']}",
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
            all_conflicts += [f"{surgeon.full_name}: " + conflict for conflict in raw]

    return _warn_redirect("/admin/meetings", all_conflicts)


@router.post("/meetings/{meeting_id}/delete")
def delete_meeting(meeting_id: int, db: Session = Depends(get_db), admin=Depends(get_current_admin)):
    meeting = db.get(Meeting, meeting_id)
    if not meeting:
        return RedirectResponse("/admin/meetings?msg=not_found", status_code=303)
    attendee_ids = [row.surgeon_id for row in meeting.attendees]
    target_surgeon_ids = _target_surgeon_ids(db, attendee_ids)
    meeting_date = meeting.date
    meeting_title = meeting.title
    db.delete(meeting)
    db.commit()
    for surgeon_id in target_surgeon_ids:
        send_push_to_surgeon(
            surgeon_id,
            "Schedule updated",
            f"Meeting removed {meeting_date.strftime('%a')}: {meeting_title}",
            db,
            url="/surgeon/schedule",
        )
    return RedirectResponse("/admin/meetings", status_code=303)
