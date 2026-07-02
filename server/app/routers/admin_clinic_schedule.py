"""Admin clinic schedule routes."""
from datetime import date

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from ..admin_clinic_schedule_service import (
    assign_clinic as assign_clinic_service,
    clear_clinic as clear_clinic_service,
    copy_clinic_week as copy_clinic_week_service,
    page_data,
)
from ..auth import get_current_admin
from ..database import get_db
from ..jinja_env import templates
from ..models import Surgeon
from ..surgeon_visibility import surgeon_is_visible
from .admin import _base, _sort_surgeons_physicians_first, _warn_redirect

router = APIRouter(prefix="/admin")


@router.get("/clinic-schedule", response_class=HTMLResponse)
def clinic_schedule_page(
    request: Request,
    week_offset: int = 0,
    db: Session = Depends(get_db),
    admin=Depends(get_current_admin),
):
    surgeons = [
        row for row in db.query(Surgeon).filter(Surgeon.is_active == True).order_by(Surgeon.last_name).all()
        if surgeon_is_visible(row)
    ]
    surgeons = _sort_surgeons_physicians_first(surgeons)
    data = page_data(db, week_offset)

    return templates.TemplateResponse("admin/clinic_schedule.html", _base(
        request, admin, db=db,
        surgeons=surgeons,
        clinics=data["clinic_locations"],
        hospitals=data["hospital_locations"],
        all_locations=data["all_locations"],
        week_days=data["week_days"],
        sched_map=data["sched_map"],
        surgical_map=data["surgical_map"],
        surgical_cases_json=data["surgical_cases_json"],
        week_offset=week_offset,
        locations=data["all_locations"],
        today=data["today"],
    ))


@router.post("/clinic-schedule/assign")
def assign_clinic(
    schedule_date: str = Form(...),
    surgeon_id: int = Form(...),
    location_choice: str = Form(...),
    session: str = Form("full"),
    notes: str = Form(""),
    week_offset: int = Form(0),
    db: Session = Depends(get_db),
    admin=Depends(get_current_admin),
):
    d = date.fromisoformat(schedule_date)
    conflicts = assign_clinic_service(db, d, surgeon_id, location_choice, session, notes)
    return _warn_redirect(f"/admin/clinic-schedule?week_offset={week_offset}", conflicts)


@router.post("/clinic-schedule/clear")
def clear_clinic(
    schedule_id: int = Form(...),
    week_offset: int = Form(0),
    db: Session = Depends(get_db),
    admin=Depends(get_current_admin),
):
    clear_clinic_service(db, schedule_id)
    return RedirectResponse(f"/admin/clinic-schedule?week_offset={week_offset}", status_code=303)


@router.post("/clinic-schedule/copy-week")
def copy_clinic_week(
    source_offset: int = Form(...),
    surgeon_id: str = Form("all"),
    db: Session = Depends(get_db),
    admin=Depends(get_current_admin),
):
    """Copy the source week's clinic schedule to the next week."""
    result = copy_clinic_week_service(db, source_offset, surgeon_id)
    if not result["ok"]:
        return RedirectResponse(
            f"/admin/clinic-schedule?week_offset={source_offset}&warn=Invalid+surgeon+selection",
            status_code=303,
        )
    return RedirectResponse(
        f"/admin/clinic-schedule?week_offset={result['next_offset']}&msg=week_copied&created={result['created']}&replaced={result['replaced']}",
        status_code=303,
    )
