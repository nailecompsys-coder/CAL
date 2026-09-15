"""Needs attention: schedule flags with CAL vs OCR compare."""

from datetime import date, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from ..auth import get_current_admin
from ..database import get_db
from ..ingest_fix_service import parked_ingest_cases
from ..jinja_env import templates
from ..models import Surgeon
from ..or_block_service import recent_schedule_changes
from ..practice_time import practice_today
from ..schedule_flag_compare_service import enrich_flag_list_row
from ..surgeon_visibility import surgeon_is_visible
from .admin import _base, _sort_surgeons_physicians_first

router = APIRouter(prefix="/admin")


def _optional_int(value: Optional[str]) -> Optional[int]:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return int(text)
    except ValueError:
        return None


@router.get("/scheduler-availability", response_class=HTMLResponse)
def scheduler_availability_page(
    request: Request,
    start: str = "",
    days: int = 14,
    surgeon_id: Optional[str] = Query(default=None),
    db: Session = Depends(get_db),
    admin=Depends(get_current_admin),
):
    try:
        start_date = date.fromisoformat(start) if start else practice_today()
    except ValueError:
        start_date = practice_today()
    days = min(max(days, 1), 45)
    end_date = start_date + timedelta(days=days - 1)
    selected_surgeon_id = _optional_int(surgeon_id)

    surgeons = [
        row for row in db.query(Surgeon).filter(Surgeon.is_active == True).order_by(Surgeon.last_name).all()  # noqa: E712
        if surgeon_is_visible(row) and (row.staff_type or "physician") == "physician"
    ]
    surgeons = _sort_surgeons_physicians_first(surgeons)

    from ..admin_settings_page_service import reconcile_stale_schedule_flag_notifications
    reconcile_stale_schedule_flag_notifications(db)

    schedule_flags = []
    for row in recent_schedule_changes(db, hours=24 * 90):
        if row.get("type") != "desk_or_schedule_flag":
            continue
        if row.get("date"):
            try:
                flag_day = date.fromisoformat(str(row["date"])[:10])
            except ValueError:
                flag_day = None
            if flag_day and (flag_day < start_date or flag_day > end_date):
                continue
        if selected_surgeon_id:
            selected = next((s for s in surgeons if s.id == selected_surgeon_id), None)
            if selected and row.get("surgeon") != selected.full_name:
                continue
        schedule_flags.append(enrich_flag_list_row(db, row))

    parked_count = len(parked_ingest_cases(db, start=start_date, end=end_date))
    return templates.TemplateResponse("admin/scheduler_availability.html", _base(
        request,
        admin,
        db=db,
        start_date=start_date,
        end_date=end_date,
        days=days,
        selected_surgeon_id=selected_surgeon_id,
        surgeons=surgeons,
        schedule_flags=schedule_flags,
        parked_count=parked_count,
    ))
