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
    dayoff_is_current_or_future,
    delete_dayoff as delete_dayoff_service,
    deny_dayoff as deny_dayoff_service,
    edit_dayoff as edit_dayoff_service,
    gantt_rows,
    month_window,
    pending_conflict_map,
)
from ..auth import get_current_admin
from ..database import get_db
from ..jinja_env import templates
from ..models import DayOff, Surgeon
from ..surgeon_visibility import surgeon_is_visible
from .admin import _base, _sort_surgeons_physicians_first, _warn_redirect

router = APIRouter(prefix="/admin")


@router.get("/daysoff", response_class=HTMLResponse)
def daysoff_page(
    request: Request,
    surgeon_id: Optional[int] = None,
    month_offset: int = 0,
    db: Session = Depends(get_db),
    admin=Depends(get_current_admin),
):
    month = month_window(month_offset)
    today = month["today"]
    surgeons = [
        row for row in db.query(Surgeon).filter(Surgeon.is_active == True).order_by(Surgeon.last_name).all()
        if surgeon_is_visible(row)
    ]
    surgeons = _sort_surgeons_physicians_first(surgeons)
    gantt_surgeons = [s for s in surgeons if (not surgeon_id) or s.id == surgeon_id]

    q = db.query(DayOff)
    if surgeon_id:
        q = q.filter(DayOff.surgeon_id == surgeon_id)

    # Pending list: still today-forward for approve workflow
    pending = [
        row for row in q.filter(
            DayOff.status == "pending",
            DayOff.end_date >= today,
        ).order_by(DayOff.start_date).all()
        if dayoff_is_current_or_future(row, today) and surgeon_is_visible(row.surgeon)
    ]

    # Gantt: approved + pending that overlap the visible month
    month_dayoffs = [
        row for row in q.filter(
            DayOff.status.in_(("approved", "pending")),
            DayOff.start_date <= month["month_end"],
            DayOff.end_date >= month["month_start"],
        ).order_by(DayOff.start_date).all()
        if surgeon_is_visible(row.surgeon)
    ]
    coverage_rows = gantt_rows(
        gantt_surgeons,
        month_dayoffs,
        month_start=month["month_start"],
        month_end=month["month_end"],
        days_in_month=month["days_in_month"],
    )
    conflict_map = pending_conflict_map(db, pending)

    return templates.TemplateResponse("admin/daysoff.html", _base(
        request, admin, db=db,
        pending=pending,
        conflict_map=conflict_map,
        surgeons=surgeons,
        selected_surgeon_id=surgeon_id,
        month_offset=month_offset,
        month_label=month["month_label"],
        month_start=month["month_start"],
        month_end=month["month_end"],
        days_in_month=month["days_in_month"],
        day_numbers=month["day_numbers"],
        today=today,
        coverage_rows=coverage_rows,
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
