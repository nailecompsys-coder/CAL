"""Admin portal meeting management routes."""

from datetime import date, timedelta

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from ..admin_meeting_service import (
    calendar_events_by_day,
    create_meeting as create_meeting_service,
    delete_meeting as delete_meeting_service,
    month_picker_options,
    month_schedule_days,
    parse_meeting_fields,
    update_meeting as update_meeting_service,
)
from ..aprima_cache_service import meetings_for_admin, sync_status_payload
from ..auth import get_current_admin
from ..database import get_db
from ..jinja_env import templates
from ..models import Meeting, Surgeon
from ..native_home_serializers import is_clinic_day_meeting, is_clinic_rotation_text
from ..surgeon_visibility import surgeon_is_visible
from .admin import _base, _sort_surgeons_physicians_first, _warn_redirect

router = APIRouter(prefix="/admin")


@router.get("/meetings", response_class=HTMLResponse)
def meetings_page(
    request: Request,
    db: Session = Depends(get_db),
    admin=Depends(get_current_admin),
    month_offset: int = 0,
):
    month = month_schedule_days(month_offset)
    schedule_days = month["schedule_days"]
    # Surgery One / clinic rotation rows live in Meetings historically but are not meetings.
    meetings = [
        row
        for row in db.query(Meeting).filter(
            Meeting.date >= month["month_start"],
            Meeting.date <= month["month_end"],
        ).order_by(Meeting.date, Meeting.start_time).all()
        if not is_clinic_day_meeting(row)
    ]
    surgeons = [
        row for row in db.query(Surgeon).filter(Surgeon.is_active == True).order_by(Surgeon.last_name).all()
        if surgeon_is_visible(row)
    ]
    surgeons = _sort_surgeons_physicians_first(surgeons)
    aprima = meetings_for_admin(db, month["month_start"], month["month_end"])
    aprima_meetings = [
        row
        for row in (aprima.get("meetings") or [])
        if not is_clinic_rotation_text(
            title=row.get("title") or "",
            location=row.get("serviceSite") or row.get("room") or "",
            reason=row.get("reason") or "",
        )
    ]
    events_by_day = calendar_events_by_day(
        schedule_days=schedule_days,
        cal_meetings=meetings,
        aprima_meetings=aprima_meetings,
    )
    month_count = sum(len(events) for events in events_by_day.values())
    return templates.TemplateResponse("admin/meetings.html", _base(
        request, admin, db=db,
        meetings=meetings,
        surgeons=surgeons,
        aprima_meetings=aprima_meetings,
        aprima_warning=aprima.get("warning"),
        aprima_sync=sync_status_payload(db),
        month_offset=month_offset,
        month_label=month["month_label"],
        month_options=month_picker_options(month_offset),
        schedule_days=schedule_days,
        pad_start=month["pad_start"],
        today=month["today"],
        events_by_day=events_by_day,
        month_count=month_count,
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
    fields = parse_meeting_fields(
        title=title,
        meeting_date=meeting_date,
        start_time=start_time,
        end_time=end_time,
        location_text=location_text,
        recurrence_rule=recurrence_rule,
        notes=notes,
    )
    conflicts = create_meeting_service(db, admin.id, fields, attendee_ids, start_time)
    return _warn_redirect("/admin/meetings", conflicts)


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

    fields = parse_meeting_fields(
        title=title,
        meeting_date=meeting_date,
        start_time=start_time,
        end_time=end_time,
        location_text=location_text,
        recurrence_rule=recurrence_rule,
        notes=notes,
    )
    conflicts = update_meeting_service(db, meeting, fields, attendee_ids, start_time)
    return _warn_redirect("/admin/meetings", conflicts)


@router.post("/meetings/{meeting_id}/delete")
def delete_meeting(meeting_id: int, db: Session = Depends(get_db), admin=Depends(get_current_admin)):
    meeting = db.get(Meeting, meeting_id)
    if not meeting:
        return RedirectResponse("/admin/meetings?msg=not_found", status_code=303)
    delete_meeting_service(db, meeting)
    return RedirectResponse("/admin/meetings", status_code=303)
