"""Admin compare page: CAL Block OR vs fax OCR for one schedule flag."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from ..auth import get_current_admin
from ..database import get_db
from ..jinja_env import templates
from ..schedule_flag_compare_service import build_schedule_flag_compare
from .admin import _base

router = APIRouter(prefix="/admin")


@router.get("/schedule-flags/{event_id}", response_class=HTMLResponse)
def schedule_flag_compare_page(
    event_id: int,
    request: Request,
    db: Session = Depends(get_db),
    admin=Depends(get_current_admin),
):
    compare = build_schedule_flag_compare(db, event_id)
    if compare is None:
        return RedirectResponse("/admin/scheduler-availability?msg=missing-flag", status_code=303)
    return templates.TemplateResponse(
        "admin/schedule_flag_compare.html",
        _base(request, admin, db=db, compare=compare),
    )
