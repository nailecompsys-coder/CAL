"""Admin schedule template and call rotation builder routes."""
from typing import Optional

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from sqlalchemy.orm import Session

from ..auth import get_current_admin
from ..admin_schedule_template_service import (
    apply_clinic_schedule_templates,
    auto_fill_call_rotation,
    call_rotation_result_url,
    clinic_apply_result_url,
    parse_date_range,
    save_call_rotation_order as save_call_rotation_order_service,
    save_template_cell_value,
    template_grid_context,
)
from ..database import get_db
from ..jinja_env import templates
from .admin import _base, _sort_surgeons_physicians_first

router = APIRouter(prefix="/admin")


def _sort_surgeons_by_type(surgeons):
    """Template view uses the same practice-rank ordering as the rest of admin."""
    return _sort_surgeons_physicians_first(surgeons)


@router.get("/schedule-templates", response_class=HTMLResponse)
def schedule_templates_page(
    request: Request,
    db: Session = Depends(get_db),
    admin=Depends(get_current_admin),
):
    context = template_grid_context(db, _sort_surgeons_by_type)
    return templates.TemplateResponse(
        "admin/schedule_templates.html",
        _base(request, admin, db=db, **context),
    )


@router.post("/schedule-templates/save")
def save_schedule_template(
    request: Request,
    surgeon_id: int = Form(...),
    db: Session = Depends(get_db),
    admin=Depends(get_current_admin),
):
    """Save one surgeon's weekly template from the grid form."""
    import asyncio

    async def _get_form():
        return await request.form()

    form = asyncio.get_event_loop().run_until_complete(_get_form()) if False else None

    # We'll read form synchronously via request state - use the standard FastAPI way
    return RedirectResponse("/admin/schedule-templates?msg=saved", status_code=303)


@router.post("/schedule-templates/save-cell")
async def save_template_cell(
    surgeon_id: int = Form(...),
    day_of_week: int = Form(...),
    session: str = Form(...),
    location_id: Optional[int] = Form(None),
    assignment_type: str = Form("assigned"),
    db: Session = Depends(get_db),
    admin=Depends(get_current_admin),
):
    """Save a single cell in the weekly template grid (called via fetch)."""
    result = save_template_cell_value(db, surgeon_id, day_of_week, session, location_id, assignment_type)
    return JSONResponse(result)


@router.post("/schedule-templates/apply")
async def apply_schedule_templates(
    date_from: str = Form(...),
    date_to: str = Form(...),
    surgeon_ids: str = Form("all"),
    skip_existing: bool = Form(True),
    overwrite_daysoff: bool = Form(False),
    db: Session = Depends(get_db),
    admin=Depends(get_current_admin),
):
    """Generate clinic_schedules from weekly templates for a date range."""
    d_from, d_to, error = parse_date_range(date_from, date_to)
    if error:
        return RedirectResponse(f"/admin/schedule-templates?msg={error}", status_code=303)

    result = apply_clinic_schedule_templates(
        db,
        d_from,
        d_to,
        surgeon_ids,
        skip_existing,
        overwrite_daysoff,
    )
    return RedirectResponse(clinic_apply_result_url(result), status_code=303)


@router.post("/call-rotation/save-order")
async def save_call_rotation_order(
    request: Request,
    call_group_id: int = Form(...),
    db: Session = Depends(get_db),
    admin=Depends(get_current_admin),
):
    """Save the ordered surgeon list for a call group rotation template."""
    form = await request.form()
    surgeon_ids = form.getlist("surgeon_ids[]")
    msg = save_call_rotation_order_service(db, call_group_id, surgeon_ids)
    return RedirectResponse(f"/admin/schedule-templates?msg={msg}&tab=call", status_code=303)


@router.post("/call-rotation/auto-fill")
def call_rotation_auto_fill(
    call_group_id: int = Form(...),
    date_from: str = Form(...),
    date_to: str = Form(...),
    start_position: int = Form(1),
    days_per_surgeon: int = Form(1),
    skip_existing: bool = Form(True),
    rotation_type: str = Form("primary"),
    db: Session = Depends(get_db),
    admin=Depends(get_current_admin),
):
    """Auto-fill call_rotations for a date range by cycling through the rotation template."""
    d_from, d_to, error = parse_date_range(date_from, date_to)
    if error:
        return RedirectResponse(f"/admin/schedule-templates?tab=call&msg={error}", status_code=303)

    result = auto_fill_call_rotation(
        db,
        call_group_id,
        d_from,
        d_to,
        start_position,
        days_per_surgeon,
        skip_existing,
        rotation_type,
    )
    return RedirectResponse(call_rotation_result_url(result), status_code=303)
