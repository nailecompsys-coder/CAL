"""Admin clinic schedule routes."""
from datetime import date, timedelta

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from ..auth import get_current_admin
from ..conflicts import check_conflicts
from ..database import get_db
from ..jinja_env import templates
from ..models import ClinicSchedule, Location, Surgeon, SurgicalCase
from ..push import send_push_to_surgeon
from .admin import _base, _sort_surgeons_physicians_first, _warn_redirect

router = APIRouter(prefix="/admin")


@router.get("/clinic-schedule", response_class=HTMLResponse)
def clinic_schedule_page(
    request: Request,
    week_offset: int = 0,
    db: Session = Depends(get_db),
    admin=Depends(get_current_admin),
):
    today = date.today()
    week_start = today - timedelta(days=today.weekday()) + timedelta(weeks=week_offset)
    week_days = [week_start + timedelta(days=i) for i in range(7)]

    surgeons = db.query(Surgeon).filter(Surgeon.is_active == True).order_by(Surgeon.last_name).all()
    surgeons = _sort_surgeons_physicians_first(surgeons)
    all_locations = db.query(Location).filter(
        Location.is_active == True,
    ).order_by(Location.location_type, Location.name).all()
    clinic_locations = [l for l in all_locations if l.location_type == "clinic"]
    hospital_locations = [l for l in all_locations if l.location_type == "hospital"]

    schedules = db.query(ClinicSchedule).filter(
        ClinicSchedule.date >= week_days[0],
        ClinicSchedule.date <= week_days[6],
    ).all()

    sched_map = {}
    for cs in schedules:
        sched_map.setdefault(cs.surgeon_id, {}).setdefault(cs.date, []).append(cs)

    surgical_cases = (
        db.query(SurgicalCase)
        .filter(
            SurgicalCase.date >= week_days[0],
            SurgicalCase.date <= week_days[6],
            SurgicalCase.status != "cancelled",
        )
        .order_by(SurgicalCase.date, SurgicalCase.start_time)
        .all()
    )
    surgical_map = {}
    for sc in surgical_cases:
        surgical_map.setdefault(sc.surgeon_id, {}).setdefault(sc.date, []).append(sc)

    surgical_cases_json = {}
    for sid, day_cases in surgical_map.items():
        for d, cases in day_cases.items():
            key = f"{sid}_{d.isoformat()}"
            surgical_cases_json[key] = [
                {
                    "id": c.id,
                    "surgeon_id": c.surgeon_id,
                    "date": c.date.isoformat(),
                    "start": c.start_time.strftime("%H:%M") if c.start_time else "08:00",
                    "end": c.end_time.strftime("%H:%M") if c.end_time else None,
                    "patient": c.patient_name or "",
                    "patient_dob": c.patient_dob or "",
                    "patient_phone": c.patient_phone or "",
                    "procedure": c.procedure or "",
                    "procedure_short": (c.procedure or "")[:80],
                    "location_id": c.location_id or "",
                    "room": (c.location.name if c.location else None) or c.room_text or "",
                    "room_text": c.room_text or "",
                    "status": c.status or "scheduled",
                    "notes": c.notes or "",
                }
                for c in cases
            ]

    return templates.TemplateResponse("admin/clinic_schedule.html", _base(
        request, admin, db=db,
        surgeons=surgeons,
        clinics=clinic_locations,
        hospitals=hospital_locations,
        all_locations=all_locations,
        week_days=week_days,
        sched_map=sched_map,
        surgical_map=surgical_map,
        surgical_cases_json=surgical_cases_json,
        week_offset=week_offset,
        locations=all_locations,
        today=today,
    ))


def _schedule_rows_for_slot(query, session: str):
    session = (session or "full").lower()
    if session == "full":
        return query.all()
    return query.filter(
        ClinicSchedule.session.in_([session, "full"])
    ).all()


@router.post("/clinic-schedule/assign")
def assign_clinic(
    schedule_date: str = Form(...),
    surgeon_id: int = Form(...),
    location_choice: str = Form(...),
    session: str = Form("full"),
    notes: str = Form(""),
    week_offset: int = Form(0),
    db: Session = Depends(get_db),
    admin=Depends(get_current_admin),
):
    d = date.fromisoformat(schedule_date)
    assignment_type = "off" if location_choice == "__off__" else "assigned"
    location_id = None if assignment_type == "off" else int(location_choice)
    slot_query = db.query(ClinicSchedule).filter(
        ClinicSchedule.surgeon_id == surgeon_id,
        ClinicSchedule.date == d,
    )
    for existing in _schedule_rows_for_slot(slot_query, session):
        db.delete(existing)
    db.flush()

    conflicts = []
    cs_new = ClinicSchedule(
        surgeon_id=surgeon_id,
        location_id=location_id,
        date=d,
        session=session,
        assignment_type=assignment_type,
        notes=notes,
    )
    db.add(cs_new)
    db.flush()
    db.commit()

    surgeon = db.get(Surgeon, surgeon_id)
    loc = db.get(Location, location_id) if location_id else None
    if surgeon:
        if assignment_type == "off":
            send_push_to_surgeon(
                surgeon_id,
                "Schedule Updated",
                f"{d.strftime('%b %d')}: OFF",
                db,
            )
        elif loc:
            send_push_to_surgeon(
                surgeon_id,
                "Clinic Schedule Updated",
                f"{d.strftime('%b %d')}: {loc.name}",
                db,
            )
            raw = check_conflicts(
                surgeon_id, d, d, db,
                exclude_clinic_schedule_id=cs_new.id,
                target_entity={"type": "clinic_schedule", "date": d, "session": session},
            )
            conflicts = [f"{surgeon.full_name}: " + c for c in raw]
    return _warn_redirect(f"/admin/clinic-schedule?week_offset={week_offset}", conflicts)


@router.post("/clinic-schedule/clear")
def clear_clinic(
    schedule_id: int = Form(...),
    week_offset: int = Form(0),
    db: Session = Depends(get_db),
    admin=Depends(get_current_admin),
):
    cs = db.get(ClinicSchedule, schedule_id)
    if cs:
        db.delete(cs)
        db.commit()
    return RedirectResponse(f"/admin/clinic-schedule?week_offset={week_offset}", status_code=303)


@router.post("/clinic-schedule/copy-week")
def copy_clinic_week(
    source_offset: int = Form(...),
    surgeon_id: str = Form("all"),
    db: Session = Depends(get_db),
    admin=Depends(get_current_admin),
):
    """Copy the source week's clinic schedule to the next week."""
    today = date.today()
    src_start = today - timedelta(days=today.weekday()) + timedelta(weeks=source_offset)
    src_end = src_start + timedelta(days=6)
    dst_start = src_start + timedelta(weeks=1)
    dst_end = dst_start + timedelta(days=6)

    src_query = db.query(ClinicSchedule).filter(
        ClinicSchedule.date >= src_start,
        ClinicSchedule.date <= src_end,
    )
    dst_query = db.query(ClinicSchedule).filter(
        ClinicSchedule.date >= dst_start,
        ClinicSchedule.date <= dst_end,
    )

    surgeon_filter = None
    if surgeon_id != "all":
        try:
            surgeon_filter = int(surgeon_id)
        except ValueError:
            return RedirectResponse(
                f"/admin/clinic-schedule?week_offset={source_offset}&warn=Invalid+surgeon+selection",
                status_code=303,
            )
        src_query = src_query.filter(ClinicSchedule.surgeon_id == surgeon_filter)
        dst_query = dst_query.filter(ClinicSchedule.surgeon_id == surgeon_filter)

    src_schedules = src_query.all()
    dst_schedules = dst_query.all()

    replaced = len(dst_schedules)
    for existing in dst_schedules:
        db.delete(existing)

    created = 0
    for cs in src_schedules:
        offset = (cs.date - src_start).days
        new_date = dst_start + timedelta(days=offset)
        db.add(ClinicSchedule(
            surgeon_id=cs.surgeon_id,
            location_id=cs.location_id,
            date=new_date,
            session=cs.session,
            assignment_type=cs.assignment_type or "assigned",
            notes=cs.notes,
        ))
        created += 1
    db.commit()
    next_offset = source_offset + 1
    return RedirectResponse(
        f"/admin/clinic-schedule?week_offset={next_offset}&msg=week_copied&created={created}&replaced={replaced}",
        status_code=303,
    )
