"""Admin portal call-group routes."""

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from ..auth import get_current_admin
from ..database import get_db
from ..jinja_env import templates
from ..models import CallGroup, CallGroupLocation, Location
from .admin import _base, _call_schedule_qs

router = APIRouter(prefix="/admin")


@router.get("/call-groups", response_class=HTMLResponse)
def call_groups_page(request: Request, db: Session = Depends(get_db), admin=Depends(get_current_admin)):
    call_groups = (
        db.query(CallGroup)
        .order_by(CallGroup.sort_order, CallGroup.name)
        .all()
    )
    locations = db.query(Location).filter(Location.is_active == True).order_by(Location.name).all()
    for call_group in call_groups:
        call_group._location_ids = [group_location.location_id for group_location in call_group.locations]
    return templates.TemplateResponse(
        "admin/call_groups.html",
        _base(request, admin, db=db, call_groups=call_groups, locations=locations),
    )


@router.post("/call-groups/create")
def call_group_create(
    name: str = Form(...),
    sort_order: int = Form(0),
    db: Session = Depends(get_db),
    admin=Depends(get_current_admin),
):
    call_group = CallGroup(name=name.strip(), sort_order=sort_order)
    db.add(call_group)
    db.commit()
    return RedirectResponse("/admin/call-groups?msg=created", status_code=303)


@router.post("/call-groups/create-from-schedule")
def call_group_create_from_schedule(
    request: Request,
    name: str = Form(...),
    sort_order: int = Form(0),
    month_offset: int = Form(0),
    db: Session = Depends(get_db),
    admin=Depends(get_current_admin),
):
    """Create a hospital call group and optionally add locations."""
    call_group = CallGroup(name=name.strip(), sort_order=sort_order)
    db.add(call_group)
    db.commit()
    db.refresh(call_group)
    raw_ids = request.form.getlist("location_ids")
    for location_id in raw_ids:
        try:
            loc_id = int(location_id)
            existing = db.query(CallGroupLocation).filter(
                CallGroupLocation.call_group_id == call_group.id,
                CallGroupLocation.location_id == loc_id,
            ).first()
            if not existing:
                db.add(CallGroupLocation(call_group_id=call_group.id, location_id=loc_id))
        except (ValueError, TypeError):
            continue
    db.commit()
    return RedirectResponse(
        f"/admin/call-schedule?{_call_schedule_qs(month_offset)}&msg=group_created",
        status_code=303,
    )


@router.post("/call-groups/{group_id:int}/update")
def call_group_update(
    group_id: int,
    name: str = Form(...),
    sort_order: int = Form(0),
    db: Session = Depends(get_db),
    admin=Depends(get_current_admin),
):
    call_group = db.get(CallGroup, group_id)
    if not call_group:
        raise HTTPException(404, "Call group not found")
    call_group.name = name.strip()
    call_group.sort_order = sort_order
    db.commit()
    return RedirectResponse("/admin/call-groups?msg=updated", status_code=303)


@router.post("/call-groups/{group_id:int}/delete")
def call_group_delete(
    group_id: int,
    db: Session = Depends(get_db),
    admin=Depends(get_current_admin),
):
    call_group = db.get(CallGroup, group_id)
    if not call_group:
        raise HTTPException(404, "Call group not found")
    db.delete(call_group)
    db.commit()
    return RedirectResponse("/admin/call-groups?msg=deleted", status_code=303)


@router.post("/call-groups/{group_id:int}/locations/add")
def call_group_location_add(
    group_id: int,
    location_id: int = Form(...),
    db: Session = Depends(get_db),
    admin=Depends(get_current_admin),
):
    call_group = db.get(CallGroup, group_id)
    if not call_group:
        raise HTTPException(404, "Call group not found")
    existing = db.query(CallGroupLocation).filter(
        CallGroupLocation.call_group_id == group_id,
        CallGroupLocation.location_id == location_id,
    ).first()
    if not existing:
        db.add(CallGroupLocation(call_group_id=group_id, location_id=location_id))
        db.commit()
    return RedirectResponse("/admin/call-groups?msg=location_added", status_code=303)


@router.post("/call-groups/{group_id:int}/locations/remove")
def call_group_location_remove(
    group_id: int,
    location_id: int = Form(...),
    db: Session = Depends(get_db),
    admin=Depends(get_current_admin),
):
    db.query(CallGroupLocation).filter(
        CallGroupLocation.call_group_id == group_id,
        CallGroupLocation.location_id == location_id,
    ).delete()
    db.commit()
    return RedirectResponse("/admin/call-groups?msg=location_removed", status_code=303)
