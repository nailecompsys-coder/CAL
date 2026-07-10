"""Admin Block OR workspace routes."""

from datetime import date
from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session, joinedload

from ..admin_clinic_schedule_page_service import week_days_for_offset
from ..auth import get_current_admin
from ..database import get_db
from ..jinja_env import templates
from ..models import Location, ORBlockInstance, Surgeon
from ..or_block_service import (
    BlockORCreateInput,
    block_workspace,
    create_or_blocks,
    delete_or_block_instance,
    parse_hhmm,
    session_default_times,
    update_or_block_instance,
)
from ..surgeon_visibility import surgeon_is_visible
from .admin import _base, _sort_surgeons_physicians_first

router = APIRouter(prefix="/admin")


def _redirect(week_offset: int, msg: str = "", warn: str = "", block_id: int | None = None) -> RedirectResponse:
    target = f"/admin/block-or?week_offset={week_offset}"
    if block_id:
        target += f"&block_id={block_id}"
    if msg:
        target += f"&msg={quote(msg)}"
    if warn:
        target += f"&warn={quote(warn)}"
    return RedirectResponse(target, status_code=303)


@router.get("/block-or", response_class=HTMLResponse)
def block_or_page(
    request: Request,
    week_offset: int = 0,
    block_id: int | None = None,
    db: Session = Depends(get_db),
    admin=Depends(get_current_admin),
):
    today, week_days = week_days_for_offset(week_offset)
    workspace = block_workspace(db, week_days[0], week_days[-1])
    surgeons = [
        row for row in db.query(Surgeon).filter(
            Surgeon.is_active == True,  # noqa: E712
            Surgeon.staff_type == "physician",
        ).order_by(Surgeon.sort_order, Surgeon.last_name).all()
        if surgeon_is_visible(row)
    ]
    selected_block = None
    if block_id:
        selected_block = (
            db.query(ORBlockInstance)
            .options(
                joinedload(ORBlockInstance.location),
                joinedload(ORBlockInstance.assignments),
            )
            .filter(ORBlockInstance.id == block_id)
            .first()
        )
    locations = (
        db.query(Location)
        .filter(Location.is_active == True, Location.location_type == "hospital")  # noqa: E712
        .order_by(Location.name)
        .all()
    )
    return templates.TemplateResponse("admin/block_or.html", _base(
        request,
        admin,
        db=db,
        today=today,
        week_days=week_days,
        week_offset=week_offset,
        locations=locations,
        workspace=workspace,
        surgeons=_sort_surgeons_physicians_first(surgeons),
        selected_block=selected_block,
    ))


@router.post("/block-or/create")
def block_or_create(
    name: str = Form("Open Block"),
    start_date: str = Form(...),
    end_date: str = Form(...),
    weekdays: list[int] = Form(...),
    location_ids: list[int] = Form(...),
    session: str = Form("am"),
    start_time: str = Form(""),
    end_time: str = Form(""),
    notes: str = Form(""),
    week_offset: int = Form(0),
    db: Session = Depends(get_db),
    admin=Depends(get_current_admin),
):
    if admin.role == "scheduler":
        return _redirect(week_offset, warn="Scheduler role is read-only for Block OR. Use the mobile app to assign surgeons.")
    try:
        default_start, default_end = session_default_times(session)
        payload = BlockORCreateInput(
            name=name,
            start_date=date.fromisoformat(start_date),
            end_date=date.fromisoformat(end_date),
            weekdays=weekdays,
            location_ids=location_ids,
            session=session,
            start_time=parse_hhmm(start_time, default_start),
            end_time=parse_hhmm(end_time, default_end),
            recurrence="weekly" if date.fromisoformat(start_date) != date.fromisoformat(end_date) else "once",
            notes=notes,
        )
        result = create_or_blocks(db, payload, admin.id)
    except ValueError as exc:
        return _redirect(week_offset, warn=str(exc))
    return _redirect(week_offset, msg=f"created:{result['created']}")


@router.post("/block-or/{block_id:int}/edit")
def block_or_edit(
    block_id: int,
    location_id: int = Form(...),
    session: str = Form("am"),
    start_time: str = Form(...),
    end_time: str = Form(...),
    notes: str = Form(""),
    week_offset: int = Form(0),
    db: Session = Depends(get_db),
    admin=Depends(get_current_admin),
):
    if admin.role == "scheduler":
        return _redirect(week_offset, warn="Scheduler role is read-only for Block OR.", block_id=block_id)
    try:
        default_start, default_end = session_default_times(session)
        update_or_block_instance(
            db,
            block_id,
            location_id=location_id,
            session=session,
            start_time=parse_hhmm(start_time, default_start),
            end_time=parse_hhmm(end_time, default_end),
            notes=notes,
            admin_id=admin.id,
        )
    except ValueError as exc:
        return _redirect(week_offset, warn=str(exc), block_id=block_id)
    return _redirect(week_offset, msg="updated")


@router.post("/block-or/{block_id:int}/delete")
def block_or_delete(
    block_id: int,
    week_offset: int = Form(0),
    db: Session = Depends(get_db),
    admin=Depends(get_current_admin),
):
    if admin.role == "scheduler":
        return _redirect(week_offset, warn="Scheduler role is read-only for Block OR.", block_id=block_id)
    try:
        delete_or_block_instance(db, block_id, admin_id=admin.id)
    except ValueError as exc:
        return _redirect(week_offset, warn=str(exc), block_id=block_id)
    return _redirect(week_offset, msg="deleted")
