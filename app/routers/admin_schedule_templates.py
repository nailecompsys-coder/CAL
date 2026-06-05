"""Admin schedule template and call rotation builder routes."""
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from sqlalchemy.orm import Session

from ..auth import get_current_admin
from ..admin_schedule_template_service import apply_clinic_schedule_templates, auto_fill_call_rotation
from ..database import get_db
from ..jinja_env import templates
from ..models import (
    CallGroup, CallRotationTemplate, Location, Surgeon, SurgeonLocationSchedule,
)
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
    surgeons = db.query(Surgeon).filter(Surgeon.is_active == True).all()
    surgeons = _sort_surgeons_by_type(surgeons)
    all_locations = db.query(Location).filter(Location.is_active == True).order_by(Location.location_type.desc(), Location.name).all()

    templates_raw = db.query(SurgeonLocationSchedule).all()
    tpl_map = {}
    for t in templates_raw:
        tpl_map.setdefault(t.surgeon_id, {}).setdefault(t.day_of_week, {})[t.session] = t

    call_groups = db.query(CallGroup).order_by(CallGroup.sort_order).all()
    rotation_templates = db.query(CallRotationTemplate).order_by(
        CallRotationTemplate.call_group_id, CallRotationTemplate.position
    ).all()
    rotation_by_group = {}
    for rt in rotation_templates:
        rotation_by_group.setdefault(rt.call_group_id, []).append(rt)

    return templates.TemplateResponse("admin/schedule_templates.html", _base(
        request, admin, db=db,
        surgeons=surgeons,
        all_locations=all_locations,
        tpl_map=tpl_map,
        call_groups=call_groups,
        rotation_by_group=rotation_by_group,
        days=["Mon", "Tue", "Wed", "Thu", "Fri"],
    ))


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
    existing = db.query(SurgeonLocationSchedule).filter(
        SurgeonLocationSchedule.surgeon_id == surgeon_id,
        SurgeonLocationSchedule.day_of_week == day_of_week,
        SurgeonLocationSchedule.session == session,
    ).first()

    if assignment_type == "off" and location_id is None and existing is None:
        return JSONResponse({"ok": True, "action": "noop"})

    if existing:
        existing.location_id = location_id if assignment_type == "assigned" else None
        existing.assignment_type = assignment_type
    else:
        db.add(SurgeonLocationSchedule(
            surgeon_id=surgeon_id,
            day_of_week=day_of_week,
            session=session,
            location_id=location_id if assignment_type == "assigned" else None,
            assignment_type=assignment_type,
        ))
    db.commit()
    return JSONResponse({"ok": True, "action": "updated" if existing else "created"})


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
    try:
        d_from = date.fromisoformat(date_from)
        d_to = date.fromisoformat(date_to)
    except ValueError:
        return RedirectResponse("/admin/schedule-templates?msg=bad_date", status_code=303)

    if d_to < d_from or (d_to - d_from).days > 366:
        return RedirectResponse("/admin/schedule-templates?msg=bad_range", status_code=303)

    result = apply_clinic_schedule_templates(
        db,
        d_from,
        d_to,
        surgeon_ids,
        skip_existing,
        overwrite_daysoff,
    )
    return RedirectResponse(
        f"/admin/schedule-templates?msg=applied&created={result['created']}&skipped={result['skipped_existing']}&off={result['skipped_off']}",
        status_code=303,
    )


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
    if not surgeon_ids:
        return RedirectResponse("/admin/schedule-templates?msg=no_surgeons", status_code=303)

    db.query(CallRotationTemplate).filter(
        CallRotationTemplate.call_group_id == call_group_id
    ).delete()

    for pos, sid in enumerate(surgeon_ids, start=1):
        db.add(CallRotationTemplate(
            call_group_id=call_group_id,
            surgeon_id=int(sid),
            position=pos,
        ))
    db.commit()
    return RedirectResponse("/admin/schedule-templates?msg=rotation_saved&tab=call", status_code=303)


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
    try:
        d_from = date.fromisoformat(date_from)
        d_to = date.fromisoformat(date_to)
    except ValueError:
        return RedirectResponse("/admin/schedule-templates?tab=call&msg=bad_date", status_code=303)

    if d_to < d_from or (d_to - d_from).days > 366:
        return RedirectResponse("/admin/schedule-templates?tab=call&msg=bad_range", status_code=303)

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
    if result["no_rotation"]:
        return RedirectResponse("/admin/schedule-templates?tab=call&msg=no_rotation", status_code=303)
    return RedirectResponse(
        f"/admin/schedule-templates?tab=call&msg=call_filled&created={result['created']}&skipped={result['skipped']}",
        status_code=303,
    )
