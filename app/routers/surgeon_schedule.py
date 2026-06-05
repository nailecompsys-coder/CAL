"""Surgeon schedule page routes."""
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from ..auth import get_current_surgeon
from ..database import get_db
from ..jinja_env import templates
from ..surgeon_schedule_service import build_surgeon_schedule_view
from .surgeon_context import base_context

router = APIRouter(prefix="/surgeon")


@router.get("/schedule", response_class=HTMLResponse)
def schedule(request: Request, week_offset: int = 0, db: Session = Depends(get_db), auth=Depends(get_current_surgeon)):
    surgeon, device = auth
    view = build_surgeon_schedule_view(db, surgeon, week_offset=week_offset)
    return templates.TemplateResponse(
        "surgeon/schedule.html",
        base_context(request, surgeon, device=device, **view),
    )
