"""Admin clinic group management routes."""

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from ..auth import get_current_admin
from ..database import get_db
from ..jinja_env import templates
from ..models import ClinicGroup, Location, Surgeon
from ..scheduling_guardrails_service import (
    locations_by_group,
    memberships_by_group,
    replace_clinic_group_locations,
    replace_clinic_group_members,
)
from ..surgeon_visibility import surgeon_is_visible
from .admin import _base, _sort_surgeons_physicians_first

router = APIRouter(prefix="/admin")

VALID_GROUP_TYPES = {"people", "locations"}


def _normalize_abbreviation(value: str) -> str:
    return (value or "").strip().upper()[:12]


def _parse_day_off_limit(enforce_day_off_limit: str, max_approved_off_per_day: int | None) -> tuple[bool, int]:
    enforce = enforce_day_off_limit == "on"
    limit = max(1, int(max_approved_off_per_day or 1))
    return enforce, limit


@router.get("/clinic-groups", response_class=HTMLResponse)
def clinic_groups_page(request: Request, db: Session = Depends(get_db), admin=Depends(get_current_admin)):
    groups = db.query(ClinicGroup).order_by(ClinicGroup.name).all()
    surgeons = [
        row
        for row in db.query(Surgeon).filter(Surgeon.is_active == True).order_by(Surgeon.last_name).all()  # noqa: E712
        if surgeon_is_visible(row)
    ]
    surgeons = _sort_surgeons_physicians_first(surgeons)
    locations = (
        db.query(Location)
        .filter(Location.is_active == True)  # noqa: E712
        .order_by(Location.location_type, Location.name)
        .all()
    )
    return templates.TemplateResponse("admin/clinic_groups.html", _base(
        request,
        admin,
        db=db,
        groups=groups,
        surgeons=surgeons,
        locations=locations,
        memberships=memberships_by_group(db),
        location_memberships=locations_by_group(db),
    ))


@router.post("/clinic-groups/create")
def create_clinic_group(
    name: str = Form(...),
    abbreviation: str = Form(...),
    group_type: str = Form("people"),
    enforce_day_off_limit: str = Form(""),
    max_approved_off_per_day: int = Form(1),
    is_active: str = Form("on"),
    surgeon_ids: list[int] = Form(default=[]),
    location_ids: list[int] = Form(default=[]),
    db: Session = Depends(get_db),
    admin=Depends(get_current_admin),
):
    cleaned_name = name.strip()
    cleaned_abbr = _normalize_abbreviation(abbreviation)
    cleaned_type = (group_type or "people").strip().lower()
    if not cleaned_name or not cleaned_abbr:
        raise HTTPException(400, "Name and abbreviation are required")
    if cleaned_type not in VALID_GROUP_TYPES:
        raise HTTPException(400, "Invalid group type")
    existing = db.query(ClinicGroup).filter(ClinicGroup.name == cleaned_name).first()
    if existing:
        return RedirectResponse("/admin/clinic-groups?msg=duplicate", status_code=303)

    enforce, limit = _parse_day_off_limit(enforce_day_off_limit, max_approved_off_per_day)
    if cleaned_type == "locations":
        enforce = False

    group = ClinicGroup(
        name=cleaned_name,
        abbreviation=cleaned_abbr,
        group_type=cleaned_type,
        enforce_day_off_limit=enforce,
        max_approved_off_per_day=limit,
        is_active=is_active == "on",
    )
    db.add(group)
    db.commit()
    db.refresh(group)

    if cleaned_type == "people":
        replace_clinic_group_members(db, group.id, surgeon_ids)
        replace_clinic_group_locations(db, group.id, [])
    else:
        replace_clinic_group_members(db, group.id, [])
        replace_clinic_group_locations(db, group.id, location_ids)

    return RedirectResponse("/admin/clinic-groups?msg=created", status_code=303)


@router.post("/clinic-groups/{group_id:int}/update")
def update_clinic_group(
    group_id: int,
    name: str = Form(...),
    abbreviation: str = Form(...),
    group_type: str = Form("people"),
    enforce_day_off_limit: str = Form(""),
    max_approved_off_per_day: int = Form(1),
    is_active: str = Form(""),
    surgeon_ids: list[int] = Form(default=[]),
    location_ids: list[int] = Form(default=[]),
    db: Session = Depends(get_db),
    admin=Depends(get_current_admin),
):
    group = db.get(ClinicGroup, group_id)
    if not group:
        raise HTTPException(404, "Clinic group not found")

    cleaned_name = name.strip()
    cleaned_abbr = _normalize_abbreviation(abbreviation)
    cleaned_type = (group_type or group.group_type or "people").strip().lower()
    if not cleaned_name or not cleaned_abbr:
        raise HTTPException(400, "Name and abbreviation are required")
    if cleaned_type not in VALID_GROUP_TYPES:
        raise HTTPException(400, "Invalid group type")

    duplicate = (
        db.query(ClinicGroup)
        .filter(ClinicGroup.name == cleaned_name, ClinicGroup.id != group.id)
        .first()
    )
    if duplicate:
        return RedirectResponse("/admin/clinic-groups?msg=duplicate", status_code=303)

    enforce, limit = _parse_day_off_limit(enforce_day_off_limit, max_approved_off_per_day)
    if cleaned_type == "locations":
        enforce = False

    group.name = cleaned_name
    group.abbreviation = cleaned_abbr
    group.group_type = cleaned_type
    group.enforce_day_off_limit = enforce
    group.max_approved_off_per_day = limit
    group.is_active = is_active == "on"
    db.commit()

    if cleaned_type == "people":
        replace_clinic_group_members(db, group.id, surgeon_ids)
        replace_clinic_group_locations(db, group.id, [])
    else:
        replace_clinic_group_members(db, group.id, [])
        replace_clinic_group_locations(db, group.id, location_ids)

    return RedirectResponse("/admin/clinic-groups?msg=saved", status_code=303)


@router.post("/clinic-groups/{group_id:int}/delete")
def delete_clinic_group(
    group_id: int,
    db: Session = Depends(get_db),
    admin=Depends(get_current_admin),
):
    group = db.get(ClinicGroup, group_id)
    if not group:
        raise HTTPException(404, "Clinic group not found")
    db.delete(group)
    db.commit()
    return RedirectResponse("/admin/clinic-groups?msg=deleted", status_code=303)
