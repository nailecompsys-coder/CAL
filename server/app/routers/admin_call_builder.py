"""Portal Call Builder — draft month; publish through the live Call Schedule path."""

from datetime import date

from fastapi import APIRouter, Depends, Form, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from sqlalchemy.orm import Session

from ..auth import get_current_admin
from ..call_builder_service import (
    clear_draft,
    clear_draft_month,
    page_data,
    publish_changes,
    publish_draft,
    require_admin_call_builder,
    upsert_draft,
)
from ..database import get_db
from ..jinja_env import templates
from .admin import _base, _warn_redirect

router = APIRouter(prefix="/admin")


def _month_bounds(month_offset: int) -> tuple[date, date]:
    from ..admin_call_schedule_page_service import month_schedule_days
    days = month_schedule_days(month_offset)["schedule_days"]
    return days[0], days[-1]


@router.get("/call-builder", response_class=HTMLResponse)
def call_builder_page(
    request: Request,
    month_offset: int = 0,
    db: Session = Depends(get_db),
    admin=Depends(get_current_admin),
):
    require_admin_call_builder(admin)
    data = page_data(db, month_offset)
    return templates.TemplateResponse(
        "admin/call_builder.html",
        _base(request, admin, db=db, **data),
    )


@router.post("/call-builder/place")
async def call_builder_place(
    request: Request,
    db: Session = Depends(get_db),
    admin=Depends(get_current_admin),
):
    require_admin_call_builder(admin)
    body = await request.json()
    day = date.fromisoformat(body["date"])
    group_id = int(body["callGroupId"])
    raw = body.get("surgeonId")
    surgeon_id = int(raw) if raw not in (None, "", "null") else None
    row = upsert_draft(db, day=day, call_group_id=group_id, surgeon_id=surgeon_id, admin=admin)
    return JSONResponse({
        "ok": True,
        "date": day.isoformat(),
        "callGroupId": group_id,
        "surgeonId": row.surgeon_id,
    })


@router.post("/call-builder/clear")
async def call_builder_clear_cell(
    request: Request,
    db: Session = Depends(get_db),
    admin=Depends(get_current_admin),
):
    require_admin_call_builder(admin)
    body = await request.json()
    day = date.fromisoformat(body["date"])
    group_id = int(body["callGroupId"])
    clear_draft(db, day=day, call_group_id=group_id, admin=admin)
    return JSONResponse({"ok": True})


@router.post("/call-builder/clear-month")
def call_builder_clear_month(
    month_offset: int = Form(0),
    db: Session = Depends(get_db),
    admin=Depends(get_current_admin),
):
    require_admin_call_builder(admin)
    start, end = _month_bounds(month_offset)
    clear_draft_month(db, start=start, end=end, admin=admin)
    return RedirectResponse(f"/admin/call-builder?month_offset={month_offset}", status_code=303)


@router.get("/call-builder/publish-preview")
def call_builder_publish_preview(
    month_offset: int = Query(0),
    db: Session = Depends(get_db),
    admin=Depends(get_current_admin),
):
    require_admin_call_builder(admin)
    start, end = _month_bounds(month_offset)
    return {"changes": publish_changes(db, start, end)}


@router.post("/call-builder/publish")
def call_builder_publish(
    month_offset: int = Form(0),
    db: Session = Depends(get_db),
    admin=Depends(get_current_admin),
):
    require_admin_call_builder(admin)
    start, end = _month_bounds(month_offset)
    warnings = publish_draft(db, start=start, end=end, admin=admin)
    target = f"/admin/call-builder?month_offset={month_offset}&msg=published"
    return _warn_redirect(target, warnings)
