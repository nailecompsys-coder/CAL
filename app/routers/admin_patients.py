"""Admin portal patient-assignment routes."""

from datetime import date

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from ..auth import get_current_admin
from ..database import get_db
from ..jinja_env import templates
from ..models import PatientAssignment, Surgeon
from ..push import send_push_to_surgeon
from .admin import _base, _sort_surgeons_physicians_first

router = APIRouter(prefix="/admin")


@router.get("/patients", response_class=HTMLResponse)
def patients_page(request: Request, for_date: str = "", db: Session = Depends(get_db), admin=Depends(get_current_admin)):
    view_date = date.fromisoformat(for_date) if for_date else date.today()
    surgeons = db.query(Surgeon).filter(Surgeon.is_active == True).order_by(Surgeon.last_name).all()
    surgeons = _sort_surgeons_physicians_first(surgeons)

    assignments = db.query(PatientAssignment).filter(
        PatientAssignment.date == view_date
    ).all()
    assign_map = {assignment.surgeon_id: assignment for assignment in assignments}

    return templates.TemplateResponse("admin/patients.html", _base(
        request,
        admin,
        db=db,
        surgeons=surgeons,
        view_date=view_date,
        assign_map=assign_map,
    ))


@router.post("/patients/save")
async def save_patients(
    request: Request,
    for_date: str = Form(...),
    db: Session = Depends(get_db),
    admin=Depends(get_current_admin),
):
    target_date = date.fromisoformat(for_date)
    form = await request.form()
    form_data = dict(form)

    surgeons = db.query(Surgeon).filter(Surgeon.is_active == True).all()
    changed_surgeon_ids = set()
    for surgeon in surgeons:
        count_key = f"patient_count_{surgeon.id}"
        notes_key = f"notes_{surgeon.id}"
        count = int(form_data.get(count_key, 0) or 0)
        notes = form_data.get(notes_key, "")

        existing = db.query(PatientAssignment).filter(
            PatientAssignment.surgeon_id == surgeon.id,
            PatientAssignment.date == target_date,
        ).first()
        if existing:
            if existing.patient_count != count or (existing.notes or "") != notes:
                changed_surgeon_ids.add(surgeon.id)
            existing.patient_count = count
            existing.notes = notes
        elif count > 0:
            changed_surgeon_ids.add(surgeon.id)
            db.add(
                PatientAssignment(
                    surgeon_id=surgeon.id,
                    date=target_date,
                    patient_count=count,
                    notes=notes,
                )
            )

    db.commit()
    for surgeon_id in changed_surgeon_ids:
        send_push_to_surgeon(
            surgeon_id,
            "Schedule updated",
            f"Patient schedule updated {target_date.strftime('%b %-d')}",
            db,
        )
    return RedirectResponse(f"/admin/patients?for_date={for_date}", status_code=303)
