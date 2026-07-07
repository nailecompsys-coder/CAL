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
    surgeon_id: str = "all",
    db: Session = Depends(get_db),
    admin=Depends(get_current_admin),
):
    all_surgeons = [
        row for row in db.query(Surgeon).filter(Surgeon.is_active == True).order_by(Surgeon.last_name).all()
        if surgeon_is_visible(row)
    ]
    all_surgeons = _sort_surgeons_physicians_first(all_surgeons)
    selected_surgeon_id = None
    if surgeon_id != "all":
        try:
            selected_surgeon_id = int(surgeon_id)
        except ValueError:
            selected_surgeon_id = None
    surgeons = all_surgeons
    if selected_surgeon_id is not None:
        surgeons = [row for row in all_surgeons if row.id == selected_surgeon_id]
    data = page_data(db, week_offset)
    copy_source_count = sum(
        len(day_rows)
        for sid, surgeon_days in data["sched_map"].items()
        if selected_surgeon_id is None or sid == selected_surgeon_id
        for day_rows in surgeon_days.values()
    )

    return templates.TemplateResponse("admin/clinic_schedule.html", _base(
        request, admin, db=db,
        surgeons=surgeons,
        all_surgeons=all_surgeons,
        selected_surgeon_id=selected_surgeon_id,
        selected_surgeon_value=str(selected_surgeon_id) if selected_surgeon_id is not None else "all",
        copy_source_count=copy_source_count,
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
    selected_surgeon_id: str = Form("all"),
    db: Session = Depends(get_db),
    admin=Depends(get_current_admin),
):
    d = date.fromisoformat(schedule_date)
    conflicts = assign_clinic_service(db, d, surgeon_id, location_choice, session, notes)
    return _warn_redirect(f"/admin/clinic-schedule?week_offset={week_offset}&surgeon_id={selected_surgeon_id}", conflicts)


@router.post("/clinic-schedule/clear")
def clear_clinic(
    schedule_id: int = Form(...),
    week_offset: int = Form(0),
    selected_surgeon_id: str = Form("all"),
    db: Session = Depends(get_db),
    admin=Depends(get_current_admin),
):
    clear_clinic_service(db, schedule_id)
    return RedirectResponse(f"/admin/clinic-schedule?week_offset={week_offset}&surgeon_id={selected_surgeon_id}", status_code=303)


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
        f"/admin/clinic-schedule?week_offset={result['next_offset']}&surgeon_id={surgeon_id}&msg=week_copied&created={result['created']}&replaced={result['replaced']}",
        status_code=303,
    )
