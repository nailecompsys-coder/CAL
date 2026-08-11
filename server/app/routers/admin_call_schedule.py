"""Admin call-schedule routes."""
from datetime import date

from fastapi import APIRouter, Depends, Form, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from ..admin_call_schedule_service import (
    assign_rotation as assign_rotation_service,
    clear_rotation as clear_rotation_service,
    copy_call_week as copy_call_week_service,
    page_data,
    parse_call_group_id,
)
from ..auth import get_current_admin
from ..call_schedule_audit_service import recent_call_schedule_audit_logs, surgeon_label
from ..database import get_db
from ..jinja_env import templates
from ..models import Surgeon
from ..surgeon_visibility import surgeon_is_visible
from .admin import _base, _call_schedule_qs, _sort_surgeons_physicians_first, _surgeon_sort_key, _warn_redirect

router = APIRouter(prefix="/admin")


@router.get("/rotations", response_class=RedirectResponse)
def _redirect_rotations(week_offset: int = 0):
    """Redirect legacy URL to call-schedule."""
    return RedirectResponse(f"/admin/call-schedule?week_offset={week_offset}", status_code=302)


@router.get("/call-schedule", response_class=HTMLResponse)
def call_schedule_page(
    request: Request,
    month_offset: int = 0,
    db: Session = Depends(get_db),
    admin=Depends(get_current_admin),
):
    surgeons = [
        row for row in db.query(Surgeon).filter(Surgeon.is_active == True).order_by(Surgeon.last_name).all()  # noqa: E712
        if surgeon_is_visible(row)
    ]
    surgeons = _sort_surgeons_physicians_first(surgeons)
    data = page_data(db, month_offset, _surgeon_sort_key)

    return templates.TemplateResponse("admin/call_schedule.html", _base(
        request,
        admin,
        db=db,
        surgeons=surgeons,
        schedule_days=data["schedule_days"],
        group_rows=data["group_rows"],
        month_offset=month_offset,
        month_label=data["month_label"],
        pad_start=data["pad_start"],
        day_off_by_date=data["day_off_by_date"],
        call_groups=data["call_groups"],
        locations=data["locations"],
        surgeon_is_visible=data["surgeon_is_visible"],
        call_group_display_color=data["call_group_display_color"],
        today=data["today"],
    ))


@router.post("/call-schedule/assign")
def assign_rotation(
    rotation_date: str = Form(...),
    surgeon_id: str = Form(""),
    rotation_type: str = Form("primary"),
    month_offset: int = Form(0),
    call_group_id: str = Form(""),
    db: Session = Depends(get_db),
    admin=Depends(get_current_admin),
):
    assignment_date = date.fromisoformat(rotation_date)
    assigned_surgeon_id = int(surgeon_id) if surgeon_id and surgeon_id.strip() else None
    call_group_id_value = parse_call_group_id(call_group_id)
    conflicts = assign_rotation_service(
        db, assignment_date, assigned_surgeon_id, call_group_id_value, admin=admin,
    )
    return _warn_redirect(f"/admin/call-schedule?{_call_schedule_qs(month_offset)}", conflicts)


@router.post("/call-schedule/reclaim-orphans")
def reclaim_orphan_rotations(
    month_offset: int = Form(0),
    db: Session = Depends(get_db),
    admin=Depends(get_current_admin),
):
    """Assign restored legacy rotations to their call groups."""
    from sqlalchemy import text

    from ..database import engine
    from ..migrate_call_groups import GROUP1_NAME, GROUP2_NAME

    with engine.begin() as conn:
        conn.execute(text("""
            UPDATE call_rotations SET call_group_id = (SELECT id FROM call_groups WHERE name = :name LIMIT 1)
            WHERE call_group_id IS NULL AND rotation_type = 'primary'
        """), {"name": GROUP1_NAME})
        conn.execute(text("""
            UPDATE call_rotations SET call_group_id = (SELECT id FROM call_groups WHERE name = :name LIMIT 1)
            WHERE call_group_id IS NULL AND rotation_type = 'backup'
        """), {"name": GROUP2_NAME})
    return RedirectResponse(
        f"/admin/call-schedule?{_call_schedule_qs(month_offset)}&msg=orphans_reclaimed",
        status_code=303,
    )


@router.post("/call-schedule/copy-week")
def copy_call_week(
    source_offset: int = Form(...),
    schedule_view: str = Form("week"),
    db: Session = Depends(get_db),
    admin=Depends(get_current_admin),
):
    """Copy this week's call assignments to the next week."""
    copied = copy_call_week_service(db, source_offset)
    return RedirectResponse(f"/admin/call-schedule?msg=week_copied&n={copied}", status_code=303)


@router.post("/call-schedule/clear")
def clear_rotation(
    rotation_date: str = Form(...),
    rotation_type: str = Form(""),
    month_offset: int = Form(0),
    call_group_id: str = Form(""),
    db: Session = Depends(get_db),
    admin=Depends(get_current_admin),
):
    assignment_date = date.fromisoformat(rotation_date)
    call_group_id_value = parse_call_group_id(call_group_id)
    clear_rotation_service(db, assignment_date, call_group_id_value, admin=admin)
    return RedirectResponse(f"/admin/call-schedule?{_call_schedule_qs(month_offset)}", status_code=303)


@router.post("/call-schedule/cover")
def assign_coverage(
    rotation_id: int = Form(...),
    covering_surgeon_id: int = Form(...),
    notes: str = Form(""),
    month_offset: int = Form(0),
    db: Session = Depends(get_db),
    admin=Depends(get_current_admin),
):
    from ..native_call_coverage_service import assign_admin_call_coverage
    from fastapi import HTTPException

    try:
        warnings = assign_admin_call_coverage(
            db, rotation_id, covering_surgeon_id, notes=notes, admin=admin,
        )
    except HTTPException as exc:
        return _warn_redirect(
            f"/admin/call-schedule?{_call_schedule_qs(month_offset)}",
            [str(exc.detail)],
        )
    return _warn_redirect(f"/admin/call-schedule?{_call_schedule_qs(month_offset)}", warnings)


@router.post("/call-schedule/cover/clear")
def clear_coverage(
    coverage_id: int = Form(...),
    month_offset: int = Form(0),
    db: Session = Depends(get_db),
    admin=Depends(get_current_admin),
):
    from ..native_call_coverage_service import cancel_admin_call_coverage
    from fastapi import HTTPException

    try:
        cancel_admin_call_coverage(db, coverage_id, admin=admin)
    except HTTPException as exc:
        return _warn_redirect(
            f"/admin/call-schedule?{_call_schedule_qs(month_offset)}",
            [str(exc.detail)],
        )
    return RedirectResponse(f"/admin/call-schedule?{_call_schedule_qs(month_offset)}", status_code=303)


@router.get("/call-audit", response_class=HTMLResponse)
def call_audit_page(
    request: Request,
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
    admin=Depends(get_current_admin),
):
    rows = recent_call_schedule_audit_logs(db, limit=limit)
    return templates.TemplateResponse("admin/call_audit.html", _base(
        request,
        admin,
        db=db,
        audit_logs=rows,
        surgeon_label=surgeon_label,
        limit=limit,
    ))
