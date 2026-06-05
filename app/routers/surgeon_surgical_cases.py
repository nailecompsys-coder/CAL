"""Surgeon surgical case actions."""
from fastapi import APIRouter, Depends, Form, HTTPException
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from ..auth import get_current_surgeon
from ..database import get_db
from ..models import SurgicalCase

router = APIRouter(prefix="/surgeon")


@router.post("/surgical-case/{case_id:int}/notes")
def save_surgical_case_notes(
    case_id: int,
    surgeon_notes: str = Form(""),
    db: Session = Depends(get_db),
    auth=Depends(get_current_surgeon),
):
    surgeon, _ = auth
    c = db.get(SurgicalCase, case_id)
    if not c or c.surgeon_id != surgeon.id:
        raise HTTPException(404, "Case not found")
    c.surgeon_notes = surgeon_notes.strip() or None
    db.commit()
    return RedirectResponse("/surgeon/schedule", status_code=303)
