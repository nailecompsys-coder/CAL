"""Admin portal day-off management routes."""

from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from ..admin_dayoff_service import (
    add_approved_dayoff,
    approve_dayoff as approve_dayoff_service,
    bulk_approve_dayoffs,
    delete_dayoff as delete_dayoff_service,
    deny_dayoff as deny_dayoff_service,
    edit_dayoff as edit_dayoff_service,
    pending_conflict_map,
    resolved_months,
)
from ..auth import get_current_admin
from ..database import get_db
from ..jinja_env import templates
from ..models import DayOff, Surgeon
from .admin import _base, _sort_surgeons_physicians_first, _warn_redirect

router = APIRouter(prefix="/admin")


@router.get("/daysoff", response_class=HTMLResponse)
def daysoff_page(request: Request, surgeon_id: Optional[int] = None, db: Session = Depends(get_db), admin=Depends(get_current_admin)):
    surgeons = db.query(Surgeon).filter(Surgeon.is_active == True).order_by(Surgeon.last_name).all()
    surgeons = _sort_surgeons_physicians_first(surgeons)

    q = db.query(DayOff)
    if surgeon_id:
        q = q.filter(DayOff.surgeon_id == surgeon_id)

    pending = q.filter(DayOff.status == "pending").order_by(DayOff.start_date).all()
    resolved = q.filter(DayOff.status != "pending").order_by(DayOff.start_date).all()

    months = resolved_months(resolved)
    conflict_map = pending_conflict_map(db, pending)

    return templates.TemplateResponse("admin/daysoff.html", _base(
        request, admin, db=db,
        pending=pending,
        months=months,
        conflict_map=conflict_map,
        surgeons=surgeons,
        selected_surgeon_id=surgeon_id,
    ))


@router.post("/daysoff/add")
def add_dayoff(
    request: Request,
    surgeon_id: int = Form(...),
    start_date: str = Form(...),
    end_date: str = Form(...),
    reason: str = Form("Vacation"),
    notes: str = Form(""),
    db: Session = Depends(get_db),
    admin=Depends(get_current_admin),
):
    try:
        start = date.fromisoformat(start_date)
        end = date.fromisoformat(end_date)
    except ValueError as exc:
        raise HTTPException(400, "Invalid date") from exc
    if end < start:
        end = start
    conflicts = add_approved_dayoff(db, surgeon_id, start, end, reason, notes, admin.id)
    return _warn_redirect("/admin/daysoff", conflicts)


@router.post("/daysoff/{dayoff_id}/approve")
def approve_dayoff(dayoff_id: int, db: Session = Depends(get_db), admin=Depends(get_current_admin)):
    conflicts = approve_dayoff_service(db, dayoff_id, admin.id)
    if conflicts is None:
        return RedirectResponse("/admin/daysoff", status_code=303)
    return _warn_redirect("/admin/daysoff", conflicts)


@router.post("/daysoff/bulk-approve")
def bulk_approve_daysoff(
    ids: list[int] = Form(...),
    db: Session = Depends(get_db),
    admin=Depends(get_current_admin),
):
    approved = bulk_approve_dayoffs(db, ids, admin.id)
    return RedirectResponse(f"/admin/daysoff?msg=bulk_approved&n={approved}", status_code=303)


@router.post("/daysoff/{dayoff_id}/deny")
def deny_dayoff(dayoff_id: int, admin_note: str = Form(""), db: Session = Depends(get_db), admin=Depends(get_current_admin)):
    deny_dayoff_service(db, dayoff_id, admin_note, admin.id)
    return RedirectResponse("/admin/daysoff", status_code=303)


@router.post("/daysoff/{dayoff_id}/edit")
def edit_dayoff(
    dayoff_id: int,
    start_date: str = Form(...),
    end_date: str = Form(...),
    reason: str = Form(""),
    notes: str = Form(""),
    db: Session = Depends(get_db),
    admin=Depends(get_current_admin),
):
    try:
        start = date.fromisoformat(start_date)
        end = date.fromisoformat(end_date)
    except ValueError:
        return RedirectResponse("/admin/daysoff", status_code=303)
    edit_dayoff_service(db, dayoff_id, start, end, reason, notes)
    return RedirectResponse("/admin/daysoff", status_code=303)


@router.post("/daysoff/{dayoff_id}/delete")
def delete_dayoff(dayoff_id: int, db: Session = Depends(get_db), admin=Depends(get_current_admin)):
    if not delete_dayoff_service(db, dayoff_id):
        return RedirectResponse("/admin/daysoff?msg=not_found", status_code=303)
    return RedirectResponse("/admin/daysoff", status_code=303)
