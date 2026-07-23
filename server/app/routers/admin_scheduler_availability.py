"""Scheduler board: Block OR capacity + non-PHI case warnings."""

from datetime import date, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from ..auth import get_current_admin
from ..database import get_db
from ..jinja_env import templates
from ..models import Surgeon
from ..or_block_service import ACTIVE_BLOCK_STATUSES, block_instances_for_range, recent_schedule_changes, serialize_block_instance
from ..scheduling_guardrails_service import scheduler_safe_rows
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
        start_date = date.fromisoformat(start) if start else date.today()
    except ValueError:
        start_date = date.today()
    days = min(max(days, 1), 45)
    end_date = start_date + timedelta(days=days - 1)
    selected_surgeon_id = _optional_int(surgeon_id)

    surgeons = [
        row for row in db.query(Surgeon).filter(Surgeon.is_active == True).order_by(Surgeon.last_name).all()
        if surgeon_is_visible(row) and (row.staff_type or "physician") == "physician"
    ]
    surgeons = _sort_surgeons_physicians_first(surgeons)

    blocks = []
    for block in block_instances_for_range(db, start_date, end_date):
        if (block.status or "") not in ACTIVE_BLOCK_STATUSES:
            continue
        payload = serialize_block_instance(block)
        if selected_surgeon_id and payload.get("status") != "open":
            assigned_ids = {
                row.get("surgeonId")
                for row in (payload.get("assignments") or [])
                if row.get("surgeonId")
            }
            if payload.get("surgeonId"):
                assigned_ids.add(payload["surgeonId"])
            if selected_surgeon_id not in assigned_ids:
                continue
        blocks.append(payload)

    open_blocks = [row for row in blocks if row.get("status") == "open"]
    assigned_blocks = [row for row in blocks if row.get("status") != "open"]
    case_rows = [
        row for row in scheduler_safe_rows(db, start_date, end_date, selected_surgeon_id)
        if row.get("warnings")
    ]
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
        schedule_flags.append(row)
    return templates.TemplateResponse("admin/scheduler_availability.html", _base(
        request,
        admin,
        db=db,
        start_date=start_date,
        end_date=end_date,
        days=days,
        selected_surgeon_id=selected_surgeon_id,
        surgeons=surgeons,
        open_blocks=open_blocks,
        assigned_blocks=assigned_blocks,
        rows=case_rows,
        schedule_flags=schedule_flags,
    ))
