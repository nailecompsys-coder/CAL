"""Admin portal meeting management routes."""

from datetime import date

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from ..admin_meeting_service import (
    create_meeting as create_meeting_service,
    delete_meeting as delete_meeting_service,
    parse_meeting_fields,
    update_meeting as update_meeting_service,
)
from ..auth import get_current_admin
from ..database import get_db
from ..jinja_env import templates
from ..models import Meeting, Surgeon
from .admin import _base, _sort_surgeons_physicians_first, _warn_redirect

router = APIRouter(prefix="/admin")


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
