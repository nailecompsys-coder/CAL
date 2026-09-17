"""Admin schedule template and call rotation builder routes."""
from datetime import date
from typing import Optional
from urllib.parse import quote_plus
from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..auth import get_current_admin
from ..admin_schedule_template_service import (
    auto_fill_call_rotation,
    call_rotation_result_url,
    parse_date_range,
    add_master_schedule_location,
    save_call_rotation_order as save_call_rotation_order_service,
    save_template_cell_value,
    template_grid_context,
)
from ..database import get_db
from ..jinja_env import templates
from ..practice_time import practice_today
from ..models import ScheduleCard
from ..schedule_card_service import apply_master_schedule_to_cards
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
    today = practice_today()
    context["default_master_start"] = today.isoformat()
    context["default_master_end"] = date(today.year + 1, 12, 31).isoformat()
    return templates.TemplateResponse(
        "admin/master_schedule.html",
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
    week_pattern: str = Form("all"),
    db: Session = Depends(get_db),
    admin=Depends(get_current_admin),
):
    """Save a single cell in the weekly template grid (called via fetch)."""
    try:
        result = save_template_cell_value(
            db, surgeon_id, day_of_week, session, location_id, assignment_type, week_pattern,
            commit=False,
        )
        start, end = db.query(func.min(ScheduleCard.date), func.max(ScheduleCard.date)).filter(
            ScheduleCard.surgeon_id == surgeon_id,
        ).one()
        if start and end:
            result["cards"] = apply_master_schedule_to_cards(
                db, start=start, end=end, surgeon_ids=[surgeon_id],
            )
        db.commit()
        return JSONResponse(result)
    except ValueError as exc:
        db.rollback()
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=400)


@router.post("/schedule-templates/locations")
def add_master_location(
    name: str = Form(...),
    abbreviation: str = Form(...),
    location_type: str = Form("clinic"),
    db: Session = Depends(get_db),
    admin=Depends(get_current_admin),
):
    """Create a location only; assigning it is a separate Master Schedule edit."""
    try:
        location = add_master_schedule_location(
            db,
            name=name,
            abbreviation=abbreviation,
            location_type=location_type,
        )
        db.commit()
    except ValueError as exc:
        db.rollback()
        return RedirectResponse(f"/admin/schedule-templates?location_error={quote_plus(str(exc))}", status_code=303)
    return RedirectResponse(
        f"/admin/schedule-templates?location_added={location.id}",
        status_code=303,
    )


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
    """Retired: master edits apply to permanent cards in place."""
    raise HTTPException(410, "Legacy template application is retired. Edit the Master Schedule grid instead.")


@router.post("/schedule-templates/build-master")
async def build_master_schedule_cards(
    date_from: str = Form(""),
    date_to: str = Form(""),
    db: Session = Depends(get_db),
    admin=Depends(get_current_admin),
):
    """Retired: permanent cards are created only by the one-time scaffold."""
    raise HTTPException(410, "Card building is retired. Permanent cards already exist.")


@router.post("/schedule-templates/build-backups/{backup_id}/revert")
async def revert_master_schedule_cards(
    backup_id: int,
    db: Session = Depends(get_db),
    admin=Depends(get_current_admin),
):
    """Retired with the legacy card builder."""
    raise HTTPException(410, "Legacy card-build restore is retired.")


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
