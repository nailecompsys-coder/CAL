"""Calendar JSON API feeds."""

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from ..api_calendar_service import build_admin_calendar_events, build_surgeon_calendar_events
from ..auth import get_current_admin, get_current_surgeon
from ..database import get_db
from .api_common import parse_iso_date_range

router = APIRouter(prefix="/api")


@router.get("/events")
def get_events(
    start: str,
    end: str,
    db: Session = Depends(get_db),
    admin=Depends(get_current_admin),
):
    start_date, end_date = parse_iso_date_range(start, end)
    return JSONResponse(build_admin_calendar_events(db, start_date, end_date))


@router.get("/my-events")
def get_my_events(
    start: str,
    end: str,
    db: Session = Depends(get_db),
    auth=Depends(get_current_surgeon),
):
    surgeon, _ = auth
    start_date, end_date = parse_iso_date_range(start, end)
    return JSONResponse(build_surgeon_calendar_events(db, surgeon, start_date, end_date))
