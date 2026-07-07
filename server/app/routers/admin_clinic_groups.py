"""Admin clinic group management routes."""

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from ..auth import get_current_admin
from ..database import get_db
from ..jinja_env import templates
from ..models import ClinicGroup, Surgeon
from ..scheduling_guardrails_service import memberships_by_group, replace_clinic_group_members
from ..surgeon_visibility import surgeon_is_visible
from .admin import _base, _sort_surgeons_physicians_first

router = APIRouter(prefix="/admin")


@router.get("/clinic-groups", response_class=HTMLResponse)
def clinic_groups_page(request: Request, db: Session = Depends(get_db), admin=Depends(get_current_admin)):
    groups = db.query(ClinicGroup).order_by(ClinicGroup.name).all()
    surgeons = [
        row for row in db.query(Surgeon).filter(Surgeon.is_active == True).order_by(Surgeon.last_name).all()
        if surgeon_is_visible(row) and (row.staff_type or "physician") == "physician"
    ]
    surgeons = _sort_surgeons_physicians_first(surgeons)
    return templates.TemplateResponse("admin/clinic_groups.html", _base(
        request,
        admin,
        db=db,
        groups=groups,
        surgeons=surgeons,
        memberships=memberships_by_group(db),
    ))


@router.post("/clinic-groups/{group_id:int}/update")
def update_clinic_group(
    group_id: int,
    name: str = Form(...),
    abbreviation: str = Form(...),
    max_approved_off_per_day: int = Form(...),
    is_active: str = Form(""),
    surgeon_ids: list[int] = Form(default=[]),
    db: Session = Depends(get_db),
    admin=Depends(get_current_admin),
):
    group = db.get(ClinicGroup, group_id)
    if group:
        group.name = name.strip()
        group.abbreviation = abbreviation.strip().upper()[:12]
        group.max_approved_off_per_day = max(1, int(max_approved_off_per_day or 1))
        group.is_active = is_active == "on"
        db.commit()
        replace_clinic_group_members(db, group.id, surgeon_ids)
    return RedirectResponse("/admin/clinic-groups?msg=saved", status_code=303)
