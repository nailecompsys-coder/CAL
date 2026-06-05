"""Surgeon PWA HTML routes."""
from datetime import date, timedelta

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session, joinedload

from .. import __version__ as app_version
from ..jinja_env import templates
from ..auth import SURGEON_ADMIN_PREVIEW_DEVICE_NAME, get_current_surgeon
from ..call_schedule_utils import (
    build_call_group_rows,
    build_merged_slot_index,
    index_rotations_by_group_date,
)
from ..database import get_db
from ..models import (
    CallGroup,
    CallRotation,
    SurgeonDayItem,
)

router = APIRouter(prefix="/surgeon")

def _base(request: Request, surgeon, device=None, **kwargs):
    desktop_preview = (
        device is not None
        and getattr(device, "device_name", None) == SURGEON_ADMIN_PREVIEW_DEVICE_NAME
    )
    return {
        "request": request,
        "surgeon": surgeon,
        "today": date.today(),
        "desktop_preview": desktop_preview,
        "app_version": app_version,
        **kwargs,
    }


def _serialize_personal(pi: SurgeonDayItem) -> dict:
    return {
        "id": pi.id,
        "title": pi.title,
        "notes": (pi.notes or "").strip(),
        "start": pi.start_time.strftime("%H:%M") if pi.start_time else None,
        "end": pi.end_time.strftime("%H:%M") if pi.end_time else None,
        "sortOrder": pi.sort_order or 0,
    }


@router.get("/register", response_class=HTMLResponse)
def register_page(request: Request, token: str = ""):
    return templates.TemplateResponse(
        "surgeon/register.html",
        {"request": request, "token": token, "app_version": app_version},
    )


@router.get("/call-schedule", response_class=HTMLResponse)
def call_schedule_page(
    request: Request,
    week_offset: int = 0,
    schedule_view: str = "week",
    db: Session = Depends(get_db),
    auth=Depends(get_current_surgeon),
):
    surgeon, device = auth
    today = date.today()
    week_start = today - timedelta(days=today.weekday()) + timedelta(weeks=week_offset)
    use_30d = schedule_view == "30d"
    if use_30d:
        schedule_days = [week_start + timedelta(days=i) for i in range(30)]
    else:
        schedule_days = [week_start + timedelta(days=i) for i in range(7)]
    schedule_view = "30d" if use_30d else "week"

    call_groups = (
        db.query(CallGroup)
        .order_by(CallGroup.sort_order, CallGroup.name, CallGroup.id)
        .all()
    )
    call_group_rows = build_call_group_rows(call_groups)
    rotations = (
        db.query(CallRotation)
        .options(
            joinedload(CallRotation.surgeon),
            joinedload(CallRotation.call_group),
        )
        .filter(
            CallRotation.date >= schedule_days[0],
            CallRotation.date <= schedule_days[-1],
        )
        .all()
    )
    call_rotation_index = index_rotations_by_group_date(rotations, call_groups)
    merged_slot_index = build_merged_slot_index(call_group_rows, call_rotation_index)

    return templates.TemplateResponse(
        "surgeon/call_schedule.html",
        _base(
            request,
            surgeon,
            device=device,
            schedule_days=schedule_days,
            schedule_view=schedule_view,
            call_groups=call_groups,
            call_group_rows=call_group_rows,
            merged_slot_index=merged_slot_index,
            week_offset=week_offset,
        ),
    )
