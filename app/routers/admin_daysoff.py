"""Admin portal day-off management routes."""

import calendar as _calendar
from collections import defaultdict
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from ..auth import get_current_admin
from ..conflicts import check_conflicts
from ..database import get_db
from ..jinja_env import templates
from ..models import CallRotation, DayOff, Surgeon
from ..push import send_push_to_surgeon
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

    month_map: dict = defaultdict(list)
    for dayoff in resolved:
        month_map[(dayoff.start_date.year, dayoff.start_date.month)].append(dayoff)
    months = [
        {"label": f"{_calendar.month_name[mo].upper()} {yr}", "records": recs}
        for (yr, mo), recs in sorted(month_map.items())
    ]

    conflict_map = {}
    for dayoff in pending:
        conflicts = db.query(CallRotation).filter(
            CallRotation.surgeon_id == dayoff.surgeon_id,
            CallRotation.date >= dayoff.start_date,
            CallRotation.date <= dayoff.end_date,
        ).all()
        conflict_map[dayoff.id] = conflicts

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
    dayoff = DayOff(
        surgeon_id=surgeon_id,
        start_date=start,
        end_date=end,
        reason=reason,
        notes=notes or None,
        status="approved",
        approved_by=admin.id,
    )
    db.add(dayoff)
    db.commit()
    send_push_to_surgeon(surgeon_id, "Day Off Added",
                         f"Admin added approved time off: {start.strftime('%b %d')}–{end.strftime('%b %d')}.", db)
    conflicts = check_conflicts(
        surgeon_id, start, end, db,
        exclude_dayoff_id=dayoff.id,
        target_entity={"type": "day_off", "start_date": start, "end_date": end},
    )
    surgeon = db.get(Surgeon, surgeon_id)
    if surgeon and conflicts:
        conflicts = [f"{surgeon.full_name}: " + c for c in conflicts]
    return _warn_redirect("/admin/daysoff", conflicts)


@router.post("/daysoff/{dayoff_id}/approve")
def approve_dayoff(dayoff_id: int, db: Session = Depends(get_db), admin=Depends(get_current_admin)):
    dayoff = db.get(DayOff, dayoff_id)
    if not dayoff:
        return RedirectResponse("/admin/daysoff", status_code=303)
    dayoff.status = "approved"
    dayoff.approved_by = admin.id
    db.commit()
    send_push_to_surgeon(dayoff.surgeon_id, "Days Off Approved",
                         f"Your request for {dayoff.start_date.strftime('%b %d')}–{dayoff.end_date.strftime('%b %d')} was approved.", db)
    conflicts = check_conflicts(
        dayoff.surgeon_id, dayoff.start_date, dayoff.end_date, db,
        exclude_dayoff_id=dayoff.id,
        target_entity={
            "type": "day_off",
            "start_date": dayoff.start_date,
            "end_date": dayoff.end_date,
        },
    )
    surgeon = db.get(Surgeon, dayoff.surgeon_id)
    if surgeon and conflicts:
        conflicts = [f"{surgeon.full_name}: " + c for c in conflicts]
    return _warn_redirect("/admin/daysoff", conflicts)


@router.post("/daysoff/bulk-approve")
def bulk_approve_daysoff(
    ids: list[int] = Form(...),
    db: Session = Depends(get_db),
    admin=Depends(get_current_admin),
):
    approved = 0
    for dayoff_id in ids:
        dayoff = db.get(DayOff, dayoff_id)
        if dayoff and dayoff.status == "pending":
            dayoff.status = "approved"
            dayoff.approved_by = admin.id
            db.commit()
            send_push_to_surgeon(dayoff.surgeon_id, "Days Off Approved",
                                 f"Your request for {dayoff.start_date.strftime('%b %d')}–{dayoff.end_date.strftime('%b %d')} was approved.", db)
            approved += 1
    return RedirectResponse(f"/admin/daysoff?msg=bulk_approved&n={approved}", status_code=303)


@router.post("/daysoff/{dayoff_id}/deny")
def deny_dayoff(dayoff_id: int, admin_note: str = Form(""), db: Session = Depends(get_db), admin=Depends(get_current_admin)):
    dayoff = db.get(DayOff, dayoff_id)
    if dayoff:
        dayoff.status = "denied"
        dayoff.admin_note = admin_note or None
        dayoff.approved_by = admin.id
        db.commit()
        msg = admin_note if admin_note else f"Your request for {dayoff.start_date.strftime('%b %d')}–{dayoff.end_date.strftime('%b %d')} was not approved."
        send_push_to_surgeon(dayoff.surgeon_id, "Days Off Request", msg, db)
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
    dayoff = db.get(DayOff, dayoff_id)
    if dayoff:
        try:
            dayoff.start_date = date.fromisoformat(start_date)
            dayoff.end_date = date.fromisoformat(end_date)
        except ValueError:
            return RedirectResponse("/admin/daysoff", status_code=303)
        dayoff.reason = reason
        dayoff.notes = notes
        db.commit()
    return RedirectResponse("/admin/daysoff", status_code=303)


@router.post("/daysoff/{dayoff_id}/delete")
def delete_dayoff(dayoff_id: int, db: Session = Depends(get_db), admin=Depends(get_current_admin)):
    dayoff = db.get(DayOff, dayoff_id)
    if not dayoff:
        return RedirectResponse("/admin/daysoff?msg=not_found", status_code=303)
    db.delete(dayoff)
    db.commit()
    return RedirectResponse("/admin/daysoff", status_code=303)
