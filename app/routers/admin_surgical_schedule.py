"""Admin portal surgical schedule routes."""

import urllib.parse
from datetime import date, datetime, time, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from ..auth import get_current_admin
from ..conflicts import check_conflicts
from ..database import get_db
from ..models import SurgicalCase
from ..push import send_push_to_surgeon

router = APIRouter(prefix="/admin")


def _week_offset_for_date(target_date: date) -> int:
    today = date.today()
    week_start = today - timedelta(days=today.weekday())
    return (target_date - week_start).days // 7


@router.get("/surgical-schedule", response_class=HTMLResponse)
def surgical_schedule_redirect(
    for_date: str = "",
    admin=Depends(get_current_admin),
):
    """Redirect to unified Schedule page (clinic-schedule) with same week."""
    if for_date:
        try:
            view_date = date.fromisoformat(for_date.strip())
            today = date.today()
            week_start = today - timedelta(days=today.weekday())
            delta = (view_date - week_start).days
            week_offset = delta // 7
            return RedirectResponse(f"/admin/clinic-schedule?week_offset={week_offset}", status_code=302)
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
        parsed_date = date.fromisoformat(case_date.strip())
    except ValueError:
        return RedirectResponse("/admin/clinic-schedule?msg=invalid_date", status_code=303)
    start = datetime.strptime(start_time, "%H:%M").time() if start_time else time(8, 0)
    end = datetime.strptime(end_time, "%H:%M").time() if end_time else None
    loc_id = int(location_id) if location_id and location_id.strip() else None
    db.add(SurgicalCase(
        surgeon_id=surgeon_id,
        date=parsed_date,
        start_time=start,
        end_time=end,
        patient_name=patient_name.strip(),
        patient_dob=patient_dob.strip() or None,
        patient_phone=patient_phone.strip() or None,
        procedure=procedure.strip(),
        location_id=loc_id,
        room_text=room_text.strip() or None,
        status=status,
        notes=notes.strip() or None,
    )
    )
    db.commit()
    send_push_to_surgeon(
        surgeon_id,
        "Schedule updated",
        f"Surgery added {parsed_date.strftime('%b %-d')} {start.strftime('%-I:%M %p')}",
        db,
    )
    conflicts = check_conflicts(
        surgeon_id,
        parsed_date,
        parsed_date,
        db,
        target_entity={
            "type": "surgical_case",
            "date": parsed_date,
            "start_time": start,
            "end_time": end,
        },
    )
    offset = week_offset if week_offset is not None else _week_offset_for_date(parsed_date)
    redirect = f"/admin/clinic-schedule?week_offset={offset}&msg=added"
    if conflicts:
        redirect += "&warn=" + urllib.parse.quote(" Â· ".join(conflicts[:8]))
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
    parsed_date = date.fromisoformat(case_date)
    start = datetime.strptime(start_time, "%H:%M").time() if start_time else time(8, 0)
    end = datetime.strptime(end_time, "%H:%M").time() if end_time else None
    loc_id = int(location_id) if location_id and location_id.strip() else None
    surgical_case.surgeon_id = surgeon_id
    surgical_case.date = parsed_date
    surgical_case.start_time = start
    surgical_case.end_time = end
    surgical_case.patient_name = patient_name.strip()
    surgical_case.patient_dob = patient_dob.strip() or None
    surgical_case.patient_phone = patient_phone.strip() or None
    surgical_case.procedure = procedure.strip()
    surgical_case.location_id = loc_id
    surgical_case.room_text = room_text.strip() or None
    surgical_case.status = status
    surgical_case.notes = notes.strip() or None
    db.commit()
    send_push_to_surgeon(
        surgical_case.surgeon_id,
        "Schedule updated",
        f"Surgery updated {parsed_date.strftime('%b %-d')} {start.strftime('%-I:%M %p')}",
        db,
    )
    conflicts = check_conflicts(
        surgical_case.surgeon_id,
        parsed_date,
        parsed_date,
        db,
        exclude_surgical_case_id=case_id,
        target_entity={
            "type": "surgical_case",
            "date": parsed_date,
            "start_time": start,
            "end_time": end,
        },
    )
    offset = week_offset if week_offset is not None else _week_offset_for_date(parsed_date)
    redirect = f"/admin/clinic-schedule?week_offset={offset}&msg=updated"
    if conflicts:
        redirect += "&warn=" + urllib.parse.quote(" Â· ".join(conflicts[:8]))
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
    parsed_date = surgical_case.date
    db.delete(surgical_case)
    db.commit()
    offset = week_offset if week_offset is not None else _week_offset_for_date(parsed_date)
    return RedirectResponse(f"/admin/clinic-schedule?week_offset={offset}&msg=deleted", status_code=303)
