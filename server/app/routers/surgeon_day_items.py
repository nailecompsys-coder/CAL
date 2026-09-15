"""Surgeon personal day item API routes."""
from datetime import date, time as time_type, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..auth import get_current_surgeon
from ..database import get_db
from ..practice_time import practice_today
from ..models import SurgeonDayItem
from .surgeon_context import serialize_personal_item

router = APIRouter(prefix="/surgeon")

MAX_PERSONAL_RANGE_DAYS = 31


def _parse_opt_hhmm(s: Optional[str]):
    if not s or not str(s).strip():
        return None
    parts = str(s).strip().split(":")
    if len(parts) < 2:
        return None
    try:
        return time_type(int(parts[0]), int(parts[1]))
    except ValueError:
        return None


def _validate_item_date(d: date, today: date):
    lo = today - timedelta(days=400)
    hi = today + timedelta(days=800)
    if d < lo or d > hi:
        raise HTTPException(400, "Date out of allowed range")


def _dates_in_range(start: date, end: date) -> list[date]:
    if end < start:
        raise HTTPException(400, "End date must be on or after start date")
    span = (end - start).days + 1
    if span > MAX_PERSONAL_RANGE_DAYS:
        raise HTTPException(400, f"Personal item range cannot exceed {MAX_PERSONAL_RANGE_DAYS} days")
    return [start + timedelta(days=i) for i in range(span)]


class DayItemCreate(BaseModel):
    date: date
    end_date: Optional[date] = None
    title: str = Field(..., min_length=1, max_length=255)
    notes: Optional[str] = None
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    sort_order: int = 0


class DayItemPatch(BaseModel):
    title: Optional[str] = Field(None, max_length=255)
    notes: Optional[str] = None
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    sort_order: Optional[int] = None
    date: Optional[date] = None


@router.post("/api/day-items")
def api_create_day_item(
    body: DayItemCreate,
    db: Session = Depends(get_db),
    auth=Depends(get_current_surgeon),
):
    surgeon, _ = auth
    today = practice_today()
    end = body.end_date or body.date
    days = _dates_in_range(body.date, end)
    for day in days:
        _validate_item_date(day, today)

    title = body.title.strip()
    notes = (body.notes or "").strip() or None
    start_t = _parse_opt_hhmm(body.start_time)
    end_t = _parse_opt_hhmm(body.end_time)
    sort_order = body.sort_order or 0

    created: list[SurgeonDayItem] = []
    for day in days:
        row = SurgeonDayItem(
            surgeon_id=surgeon.id,
            date=day,
            title=title,
            notes=notes,
            start_time=start_t,
            end_time=end_t,
            sort_order=sort_order,
        )
        db.add(row)
        created.append(row)
    db.commit()
    for row in created:
        db.refresh(row)
    items = [serialize_personal_item(row) for row in created]
    return JSONResponse({
        "ok": True,
        "item": items[0],
        "items": items,
        "count": len(items),
    })


@router.patch("/api/day-items/{item_id:int}")
def api_patch_day_item(
    item_id: int,
    body: DayItemPatch,
    db: Session = Depends(get_db),
    auth=Depends(get_current_surgeon),
):
    surgeon, _ = auth
    row = db.get(SurgeonDayItem, item_id)
    if not row or row.surgeon_id != surgeon.id:
        raise HTTPException(404, "Not found")
    today = practice_today()
    if body.date is not None:
        _validate_item_date(body.date, today)
        row.date = body.date
    if body.title is not None:
        row.title = body.title.strip()
        if not row.title:
            raise HTTPException(400, "Title required")
    if body.notes is not None:
        row.notes = body.notes.strip() or None
    if body.start_time is not None:
        row.start_time = _parse_opt_hhmm(body.start_time)
    if body.end_time is not None:
        row.end_time = _parse_opt_hhmm(body.end_time)
    if body.sort_order is not None:
        row.sort_order = body.sort_order
    db.commit()
    db.refresh(row)
    return JSONResponse({"ok": True, "item": serialize_personal_item(row)})


@router.delete("/api/day-items/{item_id:int}")
def api_delete_day_item(
    item_id: int,
    db: Session = Depends(get_db),
    auth=Depends(get_current_surgeon),
):
    surgeon, _ = auth
    row = db.get(SurgeonDayItem, item_id)
    if not row or row.surgeon_id != surgeon.id:
        raise HTTPException(404, "Not found")
    db.delete(row)
    db.commit()
    return JSONResponse({"ok": True})
