"""Settings → Time-off Groups.

A group is a set of surgeons with two counts: how many off at once turns a
request yellow, and how many turns it red (Chris's rule). Nothing is blocked:
red shows the surgeon who is off first and alerts Shannon when it is sent. "Whole practice"
counts every active physician without a member list. Counting happens in
sql/time_off_capacity.sql.

The old location groups are not shown here; their rows are left untouched.
"""

from fastapi import APIRouter, Depends, Form, HTTPException, Request
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

PAGE = "/admin/clinic-groups"


def _normalize_abbreviation(value: str) -> str:
    return (value or "").strip().upper()[:12]


def _count(value: str) -> int | None:
    """Blank means no limit at that color."""
    value = (value or "").strip()
    if not value:
        return None
    try:
        number = int(value)
    except ValueError:
        return None
    return max(1, min(number, 50))


def _limits(yellow_at_off: str, red_at_off: str) -> tuple[int | None, int | None] | None:
    yellow, red = _count(yellow_at_off), _count(red_at_off)
    if yellow is not None and red is not None and red <= yellow:
        return None
    return yellow, red


def _people_groups(db: Session) -> list[ClinicGroup]:
    groups = db.query(ClinicGroup).filter(ClinicGroup.group_type == "people").all()
    return sorted(groups, key=lambda g: (not g.applies_to_all, g.name.lower()))


@router.get("/clinic-groups", response_class=HTMLResponse)
def clinic_groups_page(request: Request, db: Session = Depends(get_db), admin=Depends(get_current_admin)):
    surgeons = [
        row
        for row in db.query(Surgeon).filter(Surgeon.is_active == True).order_by(Surgeon.last_name).all()  # noqa: E712
        if surgeon_is_visible(row)
    ]
    return templates.TemplateResponse("admin/clinic_groups.html", _base(
        request,
        admin,
        db=db,
        groups=_people_groups(db),
        surgeons=_sort_surgeons_physicians_first(surgeons),
        memberships=memberships_by_group(db),
    ))


@router.post("/clinic-groups/create")
def create_clinic_group(
    name: str = Form(...),
    abbreviation: str = Form(...),
    yellow_at_off: str = Form(""),
    red_at_off: str = Form(""),
    is_active: str = Form("on"),
    surgeon_ids: list[int] = Form(default=[]),
    db: Session = Depends(get_db),
    admin=Depends(get_current_admin),
):
    cleaned_name = name.strip()
    cleaned_abbr = _normalize_abbreviation(abbreviation)
    if not cleaned_name or not cleaned_abbr:
        raise HTTPException(400, "Name and abbreviation are required")
    if db.query(ClinicGroup).filter(ClinicGroup.name == cleaned_name).first():
        return RedirectResponse(f"{PAGE}?msg=duplicate", status_code=303)
    limits = _limits(yellow_at_off, red_at_off)
    if limits is None:
        return RedirectResponse(f"{PAGE}?msg=order", status_code=303)

    group = ClinicGroup(
        name=cleaned_name,
        abbreviation=cleaned_abbr,
        group_type="people",
        enforce_day_off_limit=False,
        max_approved_off_per_day=1,
        yellow_at_off=limits[0],
        red_at_off=limits[1],
        applies_to_all=False,
        is_active=is_active == "on",
    )
    db.add(group)
    db.commit()
    db.refresh(group)
    replace_clinic_group_members(db, group.id, surgeon_ids)
    return RedirectResponse(f"{PAGE}?msg=created", status_code=303)


@router.post("/clinic-groups/{group_id:int}/update")
def update_clinic_group(
    group_id: int,
    name: str = Form(...),
    abbreviation: str = Form(...),
    yellow_at_off: str = Form(""),
    red_at_off: str = Form(""),
    is_active: str = Form(""),
    surgeon_ids: list[int] = Form(default=[]),
    db: Session = Depends(get_db),
    admin=Depends(get_current_admin),
):
    group = db.get(ClinicGroup, group_id)
    if not group or group.group_type != "people":
        raise HTTPException(404, "Time-off group not found")

    cleaned_name = name.strip()
    cleaned_abbr = _normalize_abbreviation(abbreviation)
    if not cleaned_name or not cleaned_abbr:
        raise HTTPException(400, "Name and abbreviation are required")
    duplicate = (
        db.query(ClinicGroup)
        .filter(ClinicGroup.name == cleaned_name, ClinicGroup.id != group.id)
        .first()
    )
    if duplicate:
        return RedirectResponse(f"{PAGE}?msg=duplicate", status_code=303)
    limits = _limits(yellow_at_off, red_at_off)
    if limits is None:
        return RedirectResponse(f"{PAGE}?msg=order", status_code=303)

    group.name = cleaned_name
    group.abbreviation = cleaned_abbr
    group.yellow_at_off, group.red_at_off = limits
    group.enforce_day_off_limit = False
    group.is_active = is_active == "on"
    db.commit()
    # Whole practice counts everyone; it never keeps a member list.
    replace_clinic_group_members(db, group.id, [] if group.applies_to_all else surgeon_ids)
    return RedirectResponse(f"{PAGE}?msg=saved", status_code=303)


@router.post("/clinic-groups/{group_id:int}/delete")
def delete_clinic_group(
    group_id: int,
    db: Session = Depends(get_db),
    admin=Depends(get_current_admin),
):
    group = db.get(ClinicGroup, group_id)
    if not group or group.group_type != "people":
        raise HTTPException(404, "Time-off group not found")
    if group.applies_to_all:
        # Turn it off with the Active box instead; the practice-wide rule stays defined.
        return RedirectResponse(f"{PAGE}?msg=keep_whole", status_code=303)
    db.delete(group)
    db.commit()
    return RedirectResponse(f"{PAGE}?msg=deleted", status_code=303)


@router.post("/clinic-groups/exempt")
def save_time_off_exempt(
    surgeon_ids: list[int] = Form(default=[]),
    db: Session = Depends(get_db),
    admin=Depends(get_current_admin),
):
    """Exempt surgeons are outside every time-off group rule (Chris: e.g. CJ)."""
    chosen = set(surgeon_ids)
    for surgeon in db.query(Surgeon).filter(Surgeon.is_active == True).all():  # noqa: E712
        surgeon.time_off_exempt = surgeon.id in chosen
    db.commit()
    return RedirectResponse(f"{PAGE}?msg=saved", status_code=303)
