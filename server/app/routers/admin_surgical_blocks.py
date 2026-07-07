"""Admin surgical block management routes."""

from datetime import datetime

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from ..auth import get_current_admin
from ..database import get_db
from ..jinja_env import templates
from ..models import Location, Surgeon, SurgicalBlock
from ..surgeon_visibility import surgeon_is_visible
from .admin import _base, _sort_surgeons_physicians_first

router = APIRouter(prefix="/admin")


@router.get("/surgical-blocks", response_class=HTMLResponse)
def surgical_blocks_page(request: Request, db: Session = Depends(get_db), admin=Depends(get_current_admin)):
    surgeons = [
        row for row in db.query(Surgeon).filter(Surgeon.is_active == True).order_by(Surgeon.last_name).all()
        if surgeon_is_visible(row) and (row.staff_type or "physician") == "physician"
    ]
    locations = db.query(Location).filter(Location.is_active == True).order_by(Location.name).all()
    blocks = (
        db.query(SurgicalBlock)
        .order_by(SurgicalBlock.day_of_week, SurgicalBlock.block_date, SurgicalBlock.start_time)
        .all()
    )
    return templates.TemplateResponse("admin/surgical_blocks.html", _base(
        request,
        admin,
        db=db,
        surgeons=_sort_surgeons_physicians_first(surgeons),
        locations=locations,
        blocks=blocks,
        weekdays=["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"],
    ))


@router.post("/surgical-blocks/add")
def add_surgical_block(
    surgeon_id: int = Form(...),
    location_id: str = Form(""),
    day_of_week: str = Form(""),
    block_date: str = Form(""),
    start_time: str = Form(...),
    end_time: str = Form(...),
    recurrence: str = Form("weekly"),
    notes: str = Form(""),
    db: Session = Depends(get_db),
    admin=Depends(get_current_admin),
):
    parsed_date = datetime.strptime(block_date, "%Y-%m-%d").date() if block_date else None
    parsed_weekday = int(day_of_week) if day_of_week != "" else None
    if recurrence == "once":
        parsed_weekday = None
    else:
        parsed_date = None
    db.add(SurgicalBlock(
        surgeon_id=surgeon_id,
        location_id=int(location_id) if location_id else None,
        day_of_week=parsed_weekday,
        block_date=parsed_date,
        start_time=datetime.strptime(start_time, "%H:%M").time(),
        end_time=datetime.strptime(end_time, "%H:%M").time(),
        recurrence=recurrence if recurrence in {"weekly", "once"} else "weekly",
        notes=notes.strip() or None,
    ))
    db.commit()
    return RedirectResponse("/admin/surgical-blocks?msg=added", status_code=303)


@router.post("/surgical-blocks/{block_id:int}/delete")
def delete_surgical_block(block_id: int, db: Session = Depends(get_db), admin=Depends(get_current_admin)):
    block = db.get(SurgicalBlock, block_id)
    if block:
        db.delete(block)
        db.commit()
    return RedirectResponse("/admin/surgical-blocks?msg=deleted", status_code=303)
