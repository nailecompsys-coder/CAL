"""Surgeon patient assignment page routes."""
from datetime import date, timedelta

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from ..auth import get_current_surgeon
from ..database import get_db
from ..jinja_env import templates
from ..models import PatientAssignment
from .surgeon import _base

router = APIRouter(prefix="/surgeon")


@router.get("/patients", response_class=HTMLResponse)
def patients_page(request: Request, db: Session = Depends(get_db), auth=Depends(get_current_surgeon)):
    surgeon, device = auth
    today = date.today()
    today_assignment = db.query(PatientAssignment).filter(
        PatientAssignment.surgeon_id == surgeon.id,
        PatientAssignment.date == today,
    ).first()
    upcoming = db.query(PatientAssignment).filter(
        PatientAssignment.surgeon_id == surgeon.id,
        PatientAssignment.date > today,
        PatientAssignment.date <= today + timedelta(days=7),
    ).order_by(PatientAssignment.date).all()
    return templates.TemplateResponse(
        "surgeon/patients.html",
        _base(request, surgeon, device=device, today_assignment=today_assignment, upcoming=upcoming),
    )
