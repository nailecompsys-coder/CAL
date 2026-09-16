"""Admin desk ingest placement board — drag OCR misfits onto Block OR, then Save."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, Form, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..auth import get_current_admin
from ..database import get_db
from ..ingest_fix_service import (
    confirm_blank_slot_card,
    dismiss_parked_case,
    parked_ingest_cases,
    placement_blocks,
    save_ingest_placements,
    surgeons_for_fix,
)
from ..jinja_env import templates
from ..or_block_service import recent_schedule_changes
from ..practice_time import practice_today
from ..schedule_flag_compare_service import enrich_flag_list_row
from .admin import _base

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


@router.get("/ingest-fixes", response_class=HTMLResponse)
def ingest_fixes_page(
    request: Request,
    case_id: str = "",
    focus_date: str = "",
    db: Session = Depends(get_db),
    admin=Depends(get_current_admin),
):
    today = practice_today()
    focus = None
    if focus_date:
        try:
            focus = date.fromisoformat(focus_date[:10])
        except ValueError:
            focus = None
    start = (focus or today) - timedelta(days=3)
    end = (focus or today) + timedelta(days=21)
    focus_case = _optional_int(case_id)
    parked = parked_ingest_cases(db, start=start, end=end, case_id=None)
    if focus_case and not any(row["id"] == focus_case for row in parked):
        extra = parked_ingest_cases(db, case_id=focus_case)
        parked = extra + parked
    reason_counts = {}
    for row in parked:
        key = row.get("reasonKey") or "other"
        reason_counts.setdefault(key, {
            "title": row.get("reasonTitle") or "Needs review",
            "detail": row.get("reasonDetail") or "Review before placing.",
            "count": 0,
        })
        reason_counts[key]["count"] += 1
    schedule_flags = []
    for row in recent_schedule_changes(db, hours=24 * 90):
        if row.get("type") != "desk_or_schedule_flag":
            continue
        if row.get("date"):
            try:
                flag_day = date.fromisoformat(str(row["date"])[:10])
            except ValueError:
                flag_day = None
            if flag_day and (flag_day < start or flag_day > end):
                continue
        schedule_flags.append(enrich_flag_list_row(db, row))
    return templates.TemplateResponse(
        "admin/ingest_fixes.html",
        _base(
            request,
            admin,
            db=db,
            parked=parked,
            schedule_flags=schedule_flags,
            reason_counts=list(reason_counts.values()),
            blocks=placement_blocks(db, start=start, end=end),
            surgeons=surgeons_for_fix(db),
            focus_case_id=focus_case,
            start_date=start,
            end_date=end,
        ),
    )


class PlacementItem(BaseModel):
    caseId: int
    blockId: int
    surgeonId: int | None = None
    startTime: str | None = None
    room: str | None = None


class SavePlacementsBody(BaseModel):
    placements: list[PlacementItem] = Field(default_factory=list)


@router.post("/ingest-fixes/save")
def ingest_fixes_save(
    body: SavePlacementsBody,
    db: Session = Depends(get_db),
    admin=Depends(get_current_admin),
):
    result = save_ingest_placements(
        db,
        placements=[row.model_dump() for row in body.placements],
        admin_id=admin.id,
    )
    return JSONResponse(result, status_code=200 if result.get("ok") else 400)


@router.post("/ingest-fixes/{case_id}/dismiss")
def ingest_fixes_dismiss(
    case_id: int,
    db: Session = Depends(get_db),
    admin=Depends(get_current_admin),
):
    del admin
    ok = dismiss_parked_case(db, case_id=case_id)
    if not ok:
        return RedirectResponse("/admin/ingest-fixes?msg=missing", status_code=303)
    return RedirectResponse("/admin/ingest-fixes?msg=dismissed", status_code=303)


@router.post("/ingest-fixes/{case_id}/confirm-blank-slot")
def ingest_fixes_confirm_blank_slot(case_id: int, session: str = Form(...), db: Session = Depends(get_db), admin=Depends(get_current_admin)):
    del admin
    result = confirm_blank_slot_card(db, case_id=case_id, session=session)
    msg = "blank_confirmed" if result.get("ok") else "blank_error"
    return RedirectResponse(f"/admin/ingest-fixes?msg={msg}", status_code=303)
