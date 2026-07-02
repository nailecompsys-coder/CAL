"""Admin portal surgical schedule routes."""

from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from ..admin_surgical_schedule_service import (
    add_surgical_case,
    delete_surgical_case,
    surgery_fields,
    update_surgical_case,
    week_offset_for_date,
)
from ..auth import get_current_admin
from ..database import get_db
from ..models import SurgicalCase

router = APIRouter(prefix="/admin")


@router.get("/surgical-schedule", response_class=HTMLResponse)
def surgical_schedule_redirect(
    for_date: str = "",
    admin=Depends(get_current_admin),
):
    """Redirect to unified Schedule page (clinic-schedule) with same week."""
    if for_date:
        try:
            view_date = date.fromisoformat(for_date.strip())
            return RedirectResponse(f"/admin/clinic-schedule?week_offset={week_offset_for_date(view_date)}", status_code=302)
        except ValueError:
            pass
    return RedirectResponse("/admin/clinic-schedule", status_code=302)


@router.post("/surgical-schedule/add")
def surgical_case_add(
    surgeon_id: int = Form(...),
    case_date: str = Form(...),
    start_time: str = Form(...),
    patient_name: str = Form(...),
    procedure: str = Form(...),
    end_time: str = Form(""),
    patient_dob: str = Form(""),
    patient_phone: str = Form(""),
    location_id: str = Form(""),
    room_text: str = Form(""),
    status: str = Form("scheduled"),
    notes: str = Form(""),
    week_offset: Optional[int] = Form(None),
    db: Session = Depends(get_db),
    admin=Depends(get_current_admin),
):
    if not case_date or not case_date.strip():
        return RedirectResponse("/admin/clinic-schedule?msg=missing_date", status_code=303)
    try:
        fields = surgery_fields(
            surgeon_id,
            case_date,
            start_time,
            patient_name,
            procedure,
            end_time,
            patient_dob,
            patient_phone,
            location_id,
            room_text,
            status,
            notes,
        )
    except ValueError:
        return RedirectResponse("/admin/clinic-schedule?msg=invalid_date", status_code=303)
    surgical_case, warn_query = add_surgical_case(db, fields)
    offset = week_offset if week_offset is not None else week_offset_for_date(surgical_case.date)
    redirect = f"/admin/clinic-schedule?week_offset={offset}&msg=added"
    redirect += warn_query
    return RedirectResponse(redirect, status_code=303)


@router.post("/surgical-schedule/{case_id:int}/edit")
def surgical_case_edit(
    case_id: int,
    surgeon_id: int = Form(...),
    case_date: str = Form(...),
    start_time: str = Form(...),
    patient_name: str = Form(...),
    procedure: str = Form(...),
    end_time: str = Form(""),
    patient_dob: str = Form(""),
    patient_phone: str = Form(""),
    location_id: str = Form(""),
    room_text: str = Form(""),
    status: str = Form("scheduled"),
    notes: str = Form(""),
    week_offset: Optional[int] = Form(None),
    db: Session = Depends(get_db),
    admin=Depends(get_current_admin),
):
    surgical_case = db.get(SurgicalCase, case_id)
    if not surgical_case:
        raise HTTPException(404, "Case not found")
    fields = surgery_fields(
        surgeon_id,
        case_date,
        start_time,
        patient_name,
        procedure,
        end_time,
        patient_dob,
        patient_phone,
        location_id,
        room_text,
        status,
        notes,
    )
    warn_query = update_surgical_case(db, surgical_case, fields)
    offset = week_offset if week_offset is not None else week_offset_for_date(surgical_case.date)
    redirect = f"/admin/clinic-schedule?week_offset={offset}&msg=updated"
    redirect += warn_query
    return RedirectResponse(redirect, status_code=303)


@router.post("/surgical-schedule/{case_id:int}/delete")
def surgical_case_delete(
    case_id: int,
    week_offset: Optional[int] = Form(None),
    for_date: str = Form(""),
    db: Session = Depends(get_db),
    admin=Depends(get_current_admin),
):
    surgical_case = db.get(SurgicalCase, case_id)
    if not surgical_case:
        raise HTTPException(404, "Case not found")
    parsed_date = delete_surgical_case(db, surgical_case)
    offset = week_offset if week_offset is not None else week_offset_for_date(parsed_date)
    return RedirectResponse(f"/admin/clinic-schedule?week_offset={offset}&msg=deleted", status_code=303)
