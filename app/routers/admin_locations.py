"""Admin portal location management routes."""

import re

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from ..auth import get_current_admin
from ..database import get_db
from ..jinja_env import templates
from ..models import Location
from .admin import _base

router = APIRouter(prefix="/admin")

DEFAULT_CLINIC_COLOR = "#D8F6F0"
DEFAULT_HOSPITAL_COLOR = "#79CDBD"
ABBREVIATION_RE = re.compile(r"^[A-Z0-9 /&-]{1,12}$")
COLOR_RE = re.compile(r"^#[0-9A-F]{6}$")


def _normalize_location_type(value: str) -> str:
    return "hospital" if (value or "").strip().lower() == "hospital" else "clinic"


def _normalize_abbreviation(value: str) -> str | None:
    normalized = " ".join((value or "").strip().upper().split())
    if not ABBREVIATION_RE.fullmatch(normalized):
        return None
    return normalized


def _normalize_color(value: str, location_type: str) -> str | None:
    submitted = (value or "").strip().upper()
    if not submitted:
        return DEFAULT_HOSPITAL_COLOR if location_type == "hospital" else DEFAULT_CLINIC_COLOR
    return submitted if COLOR_RE.fullmatch(submitted) else None


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
            default_clinic_color=DEFAULT_CLINIC_COLOR,
            default_hospital_color=DEFAULT_HOSPITAL_COLOR,
        ),
    )


@router.post("/locations/add")
def add_location(
    name: str = Form(...),
    address: str = Form(""),
    abbreviation: str = Form(...),
    city: str = Form(""),
    phone: str = Form(""),
    location_type: str = Form("clinic"),
    color: str = Form(""),
    db: Session = Depends(get_db),
    admin=Depends(get_current_admin),
):
    location_type = _normalize_location_type(location_type)
    abbreviation_value = _normalize_abbreviation(abbreviation)
    if not abbreviation_value:
        return RedirectResponse("/admin/locations?msg=invalid_abbreviation", status_code=303)
    color_value = _normalize_color(color, location_type)
    if not color_value:
        return RedirectResponse("/admin/locations?msg=invalid_color", status_code=303)
    db.add(Location(name=name, address=address, city=city, phone=phone,
                    abbreviation=abbreviation_value, location_type=location_type,
                    color=color_value, is_active=True))
    db.commit()
    return RedirectResponse("/admin/locations?msg=added", status_code=303)


@router.post("/locations/{location_id}/edit")
def edit_location(
    location_id: int,
    name: str = Form(...),
    address: str = Form(""),
    abbreviation: str = Form(...),
    city: str = Form(""),
    phone: str = Form(""),
    location_type: str = Form("clinic"),
    color: str = Form(""),
    db: Session = Depends(get_db),
    admin=Depends(get_current_admin),
):
    loc = db.get(Location, location_id)
    if loc:
        location_type = _normalize_location_type(location_type)
        abbreviation_value = _normalize_abbreviation(abbreviation)
        if not abbreviation_value:
            return RedirectResponse("/admin/locations?msg=invalid_abbreviation", status_code=303)
        color_value = _normalize_color(color, location_type)
        if not color_value:
            return RedirectResponse("/admin/locations?msg=invalid_color", status_code=303)
        loc.name = name
        loc.address = address
        loc.abbreviation = abbreviation_value
        loc.city = city
        loc.phone = phone
        loc.location_type = location_type
        loc.color = color_value
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
