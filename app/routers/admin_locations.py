"""Admin portal location management routes."""

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from ..auth import get_current_admin
from ..database import get_db
from ..jinja_env import templates
from ..location_palette import LOCATION_PALETTE, resolve_palette_color
from ..models import Location
from .admin import _base

router = APIRouter(prefix="/admin")


@router.get("/locations", response_class=HTMLResponse)
def locations_page(request: Request, db: Session = Depends(get_db), admin=Depends(get_current_admin)):
    locations = db.query(Location).order_by(Location.location_type, Location.name).all()
    return templates.TemplateResponse(
        "admin/locations.html",
        _base(
            request,
            admin,
            db=db,
            locations=locations,
            location_palette=LOCATION_PALETTE,
        ),
    )


@router.post("/locations/add")
def add_location(
    name: str = Form(...),
    address: str = Form(""),
    city: str = Form(""),
    phone: str = Form(""),
    location_type: str = Form("clinic"),
    db: Session = Depends(get_db),
    admin=Depends(get_current_admin),
):
    palette_color = resolve_palette_color(name, location_type)
    if not palette_color:
        return RedirectResponse("/admin/locations?msg=palette_unknown", status_code=303)
    db.add(Location(name=name, address=address, city=city, phone=phone,
                    location_type=location_type, color=palette_color, is_active=True))
    db.commit()
    return RedirectResponse("/admin/locations?msg=added", status_code=303)


@router.post("/locations/{location_id}/edit")
def edit_location(
    location_id: int,
    name: str = Form(...),
    address: str = Form(""),
    city: str = Form(""),
    phone: str = Form(""),
    location_type: str = Form("clinic"),
    db: Session = Depends(get_db),
    admin=Depends(get_current_admin),
):
    loc = db.get(Location, location_id)
    if loc:
        palette_color = resolve_palette_color(name, location_type)
        if not palette_color:
            return RedirectResponse("/admin/locations?msg=palette_unknown", status_code=303)
        loc.name = name
        loc.address = address
        loc.city = city
        loc.phone = phone
        loc.location_type = location_type
        loc.color = palette_color
        db.commit()
    return RedirectResponse("/admin/locations?msg=updated", status_code=303)


@router.post("/locations/{location_id}/toggle")
def toggle_location(location_id: int, db: Session = Depends(get_db), admin=Depends(get_current_admin)):
    loc = db.get(Location, location_id)
    if loc:
        loc.is_active = not loc.is_active
        db.commit()
    return RedirectResponse("/admin/locations", status_code=303)


@router.post("/locations/{location_id}/delete")
def delete_location(location_id: int, db: Session = Depends(get_db), admin=Depends(get_current_admin)):
    loc = db.get(Location, location_id)
    if not loc:
        return RedirectResponse("/admin/locations?msg=not_found", status_code=303)
    db.delete(loc)
    db.commit()
    return RedirectResponse("/admin/locations?msg=deleted", status_code=303)
