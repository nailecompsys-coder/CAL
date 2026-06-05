"""Surgeon time-off request routes."""
import urllib.parse

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from ..auth import get_current_surgeon
from ..database import get_db
from ..jinja_env import templates
from ..surgeon_request_off_service import (
    request_off_page_data,
    submit_request_off as submit_request_off_service,
)
from .surgeon_context import base_context

router = APIRouter(prefix="/surgeon")


@router.get("/request-off", response_class=HTMLResponse)
def request_off_page(request: Request, db: Session = Depends(get_db), auth=Depends(get_current_surgeon)):
    surgeon, device = auth
    data = request_off_page_data(db, surgeon)

    return templates.TemplateResponse(
        "surgeon/request_off.html",
        base_context(
            request,
            surgeon,
            device=device,
            sections=data["sections"],
            today=data["today"],
            display_range_label=data["display_range_label"],
        ),
    )


@router.post("/request-off")
def submit_request_off(
    start_date: str = Form(...),
    end_date: str = Form(...),
    reason: str = Form(""),
    notes: str = Form(""),
    db: Session = Depends(get_db),
    auth=Depends(get_current_surgeon),
):
    surgeon, _ = auth
    result = submit_request_off_service(db, surgeon, start_date, end_date, reason, notes)
    if not result["ok"]:
        warn = urllib.parse.quote(result["warn"])
        return RedirectResponse(f"/surgeon/request-off?open=1&warn={warn}", status_code=303)
    return RedirectResponse(f"/surgeon/request-off?submitted=1{result['warn_param']}", status_code=303)
