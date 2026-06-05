"""Surgeon call schedule page routes."""
from datetime import date, timedelta

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session, joinedload

from ..auth import get_current_surgeon
from ..call_schedule_utils import (
    build_call_group_rows,
    build_merged_slot_index,
    index_rotations_by_group_date,
)
from ..database import get_db
from ..jinja_env import templates
from ..models import CallGroup, CallRotation
from .surgeon import _base

router = APIRouter(prefix="/surgeon")


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
