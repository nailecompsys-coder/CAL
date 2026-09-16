"""Admin clinic schedule routes."""
from datetime import date, timedelta

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from ..admin_clinic_schedule_service import (
    assign_clinic as assign_clinic_service,
    clear_clinic as clear_clinic_service,
    copy_clinic_week as copy_clinic_week_service,
    page_data,
)
from ..admin_surgical_schedule_service import week_offset_for_date
from ..auth import get_current_admin
from ..database import get_db
from ..jinja_env import templates
from ..models import Surgeon
from ..surgeon_visibility import surgeon_is_visible
from ..schedule_write_freeze import require_schedule_write_enabled
from .admin import _base, _sort_surgeons_physicians_first, _warn_redirect

router = APIRouter(prefix="/admin")


@router.get("/clinic-schedule", response_class=HTMLResponse)
def clinic_schedule_page(
    request: Request,
    week_offset: int = 0,
    month: str = "",
    db: Session = Depends(get_db),
    admin=Depends(get_current_admin),
):
    if month:
        try:
            first = date.fromisoformat(f"{month}-01")
            first_monday = first + timedelta(days=(7 - first.weekday()) % 7)
            week_offset = week_offset_for_date(first_monday)
        except ValueError:
            pass
    all_surgeons = [
        row for row in db.query(Surgeon).filter(Surgeon.is_active == True).order_by(Surgeon.last_name).all()
        if surgeon_is_visible(row)
    ]
    all_surgeons = _sort_surgeons_physicians_first(all_surgeons)
    surgeons = all_surgeons
    data = page_data(db, week_offset)

    return templates.TemplateResponse("admin/clinic_schedule.html", _base(
        request, admin, db=db,
        surgeons=surgeons,
        all_surgeons=all_surgeons,
        selected_surgeon_id=None,
        selected_surgeon_value="all",
        clinics=data["clinic_locations"],
        hospitals=data["hospital_locations"],
        all_locations=data["all_locations"],
        week_days=data["week_days"],
        sched_map=data["sched_map"],
        clinic_grid_slots=data["clinic_grid_slots"],
        surgical_map=data["surgical_map"],
        surgical_cases_json=data["surgical_cases_json"],
        open_or_blocks=data["open_or_blocks"],
        open_or_day_slots=data["open_or_day_slots"],
        assigned_or_blocks=data["assigned_or_blocks"],
        or_block_overlays=data.get("or_block_overlays") or {},
        clinic_fax_overlays=data.get("clinic_fax_overlays") or {},
        off_map=data.get("off_map") or {},
        off_conflicts=data.get("off_conflicts") or [],
        show_off_schedule_ids=data.get("show_off_schedule_ids") or set(),
        show_off_or_keys=data.get("show_off_or_keys") or set(),
        hide_empty_or_blocks=data.get("hide_empty_or_blocks") or {},
        conflict_keys=data.get("conflict_keys") or set(),
        synthetic_off_days=data.get("synthetic_off_days") or set(),
        week_offset=week_offset,
        view_month_value=data["week_days"][0].strftime("%Y-%m"),
        locations=data["all_locations"],
        today=data["today"],
    ))


@router.post("/clinic-schedule/assign")
def assign_clinic(
    schedule_date: str = Form(...),
    surgeon_id: int = Form(...),
    schedule_id: str = Form(""),
    location_choice: str = Form(...),
    session: str = Form("full"),
    notes: str = Form(""),
    week_offset: int = Form(0),
    selected_surgeon_id: str = Form("all"),
    db: Session = Depends(get_db),
    admin=Depends(get_current_admin),
):
    require_schedule_write_enabled()
    d = date.fromisoformat(schedule_date)
    selected_schedule_id = int(schedule_id) if schedule_id.strip() else None
    conflicts = assign_clinic_service(db, d, surgeon_id, location_choice, session, notes, selected_schedule_id)
    return _warn_redirect(f"/admin/clinic-schedule?week_offset={week_offset}&surgeon_id={selected_surgeon_id}", conflicts)


@router.post("/clinic-schedule/clear")
def clear_clinic(
    schedule_id: int = Form(...),
    week_offset: int = Form(0),
    selected_surgeon_id: str = Form("all"),
    db: Session = Depends(get_db),
    admin=Depends(get_current_admin),
):
    require_schedule_write_enabled()
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
    require_schedule_write_enabled()
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
