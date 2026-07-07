"""Read-only scheduler-safe availability view."""

from datetime import date, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from ..auth import get_current_admin
from ..database import get_db
from ..jinja_env import templates
from ..models import Surgeon
from ..scheduling_guardrails_service import scheduler_safe_rows
from ..surgeon_visibility import surgeon_is_visible
from .admin import _base, _sort_surgeons_physicians_first

router = APIRouter(prefix="/admin")


@router.get("/scheduler-availability", response_class=HTMLResponse)
def scheduler_availability_page(
    request: Request,
    start: str = "",
    days: int = 14,
    surgeon_id: Optional[int] = None,
    db: Session = Depends(get_db),
    admin=Depends(get_current_admin),
):
    try:
        start_date = date.fromisoformat(start) if start else date.today()
    except ValueError:
        start_date = date.today()
    days = min(max(days, 1), 45)
    end_date = start_date + timedelta(days=days - 1)
    surgeons = [
        row for row in db.query(Surgeon).filter(Surgeon.is_active == True).order_by(Surgeon.last_name).all()
        if surgeon_is_visible(row) and (row.staff_type or "physician") == "physician"
    ]
    surgeons = _sort_surgeons_physicians_first(surgeons)
    rows = scheduler_safe_rows(db, start_date, end_date, surgeon_id)
    return templates.TemplateResponse("admin/scheduler_availability.html", _base(
        request,
        admin,
        db=db,
        start_date=start_date,
        end_date=end_date,
        days=days,
        selected_surgeon_id=surgeon_id,
        surgeons=surgeons,
        rows=rows,
    ))
