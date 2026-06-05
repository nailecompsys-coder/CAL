"""Admin call-schedule routes."""
import calendar as _calendar
from datetime import date, timedelta

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session, joinedload

from ..auth import get_current_admin
from ..conflicts import check_conflicts
from ..database import get_db
from ..jinja_env import templates
from ..models import CallCoverage, CallGroup, CallRotation, DayOff, Location, Surgeon
from ..push import send_push_to_surgeon
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
    today = date.today()
    total_months = today.year * 12 + (today.month - 1) + month_offset
    year = total_months // 12
    month = total_months % 12 + 1
    first_day = date(year, month, 1)
    days_in_month = _calendar.monthrange(year, month)[1]
    schedule_days = [date(year, month, day) for day in range(1, days_in_month + 1)]
    month_label = first_day.strftime("%B %Y")
    pad_start = (first_day.weekday() + 1) % 7

    surgeons = db.query(Surgeon).filter(Surgeon.is_active == True).order_by(Surgeon.last_name).all()  # noqa: E712
    surgeons = _sort_surgeons_physicians_first(surgeons)

    call_groups = db.query(CallGroup).order_by(CallGroup.sort_order, CallGroup.name, CallGroup.id).all()
    rotations = (
        db.query(CallRotation)
        .options(
            joinedload(CallRotation.surgeon),
            joinedload(CallRotation.coverages).joinedload(CallCoverage.covering_surgeon),
        )
        .filter(
            CallRotation.date >= schedule_days[0],
            CallRotation.date <= schedule_days[-1],
        )
        .all()
    )

    rotation_by_group_date = {}
    for rotation in rotations:
        if rotation.call_group_id is None:
            continue
        by_date = rotation_by_group_date.setdefault(rotation.call_group_id, {})
        if rotation.date not in by_date:
            by_date[rotation.date] = rotation

    seen_names = set()
    group_rows = []
    for call_group in call_groups:
        if call_group.name in seen_names:
            continue
        seen_names.add(call_group.name)
        merged_rotations = dict(rotation_by_group_date.get(call_group.id, {}))
        for other in call_groups:
            if other.id != call_group.id and other.name == call_group.name:
                for day, rotation in rotation_by_group_date.get(other.id, {}).items():
                    if day not in merged_rotations:
                        merged_rotations[day] = rotation
        group_rows.append((call_group, merged_rotations))

    day_off_by_date = _day_off_by_date(db, schedule_days)
    locations = db.query(Location).filter(Location.is_active == True).order_by(Location.name).all()  # noqa: E712

    return templates.TemplateResponse("admin/call_schedule.html", _base(
        request,
        admin,
        db=db,
        surgeons=surgeons,
        schedule_days=schedule_days,
        group_rows=group_rows,
        month_offset=month_offset,
        month_label=month_label,
        pad_start=pad_start,
        day_off_by_date=day_off_by_date,
        call_groups=call_groups,
        locations=locations,
        today=today,
    ))


def _day_off_by_date(db: Session, schedule_days: list[date]) -> dict[date, dict[str, list[Surgeon]]]:
    day_off_rows = (
        db.query(DayOff)
        .options(joinedload(DayOff.surgeon))
        .filter(
            DayOff.start_date <= schedule_days[-1],
            DayOff.end_date >= schedule_days[0],
            DayOff.status.in_(["pending", "approved"]),
        )
        .all()
    )
    day_off_by_date: dict[date, dict[str, list[Surgeon]]] = {
        day: {"pending": [], "approved": []} for day in schedule_days
    }
    seen_day_off_initials: dict[date, dict[str, set[str]]] = {
        day: {"pending": set(), "approved": set()} for day in schedule_days
    }
    for row in day_off_rows:
        if not row.surgeon or not row.surgeon.is_active:
            continue
        status = "approved" if row.status == "approved" else "pending"
        current = max(row.start_date, schedule_days[0])
        end = min(row.end_date, schedule_days[-1])
        while current <= end:
            initials = (row.surgeon.initials or "").strip()
            if initials and initials not in seen_day_off_initials[current][status]:
                day_off_by_date[current][status].append(row.surgeon)
                seen_day_off_initials[current][status].add(initials)
            current += timedelta(days=1)
    for status_groups in day_off_by_date.values():
        for surgeons_for_status in status_groups.values():
            surgeons_for_status.sort(key=_surgeon_sort_key)
    return day_off_by_date


def _parse_call_group_id(raw: str | int | None) -> int | None:
    if raw is None:
        return None
    if isinstance(raw, int):
        return raw
    value = (raw or "").strip()
    return int(value) if value else None


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
    call_group_id_value = _parse_call_group_id(call_group_id)
    query = db.query(CallRotation).filter(CallRotation.date == assignment_date)
    if call_group_id_value is not None:
        query = query.filter(CallRotation.call_group_id == call_group_id_value)
    else:
        query = query.filter(CallRotation.call_group_id.is_(None))
    existing = query.first()
    if existing:
        existing.surgeon_id = assigned_surgeon_id
        rotation_id = existing.id
    else:
        rotation = CallRotation(
            surgeon_id=assigned_surgeon_id,
            date=assignment_date,
            rotation_type="primary",
            call_group_id=call_group_id_value,
        )
        db.add(rotation)
        db.flush()
        rotation_id = rotation.id
    db.commit()

    surgeon = db.get(Surgeon, assigned_surgeon_id) if assigned_surgeon_id else None
    if surgeon:
        send_push_to_surgeon(
            surgeon_id,
            "Schedule Update",
            f"You've been assigned on-call on {assignment_date.strftime('%b %d')}",
            db,
        )

    conflicts = []
    if surgeon and assigned_surgeon_id:
        conflicts = check_conflicts(
            assigned_surgeon_id,
            assignment_date,
            assignment_date,
            db,
            exclude_call_rotation_id=rotation_id,
            target_entity={"type": "call_rotation", "date": assignment_date},
        )
        conflicts = [f"{surgeon.full_name}: " + conflict for conflict in conflicts]
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
    today = date.today()
    week_start = today - timedelta(days=today.weekday()) + timedelta(weeks=source_offset)
    week_days_src = [week_start + timedelta(days=i) for i in range(7)]
    week_start_dst = week_start + timedelta(weeks=1)
    copied = 0
    for i in range(7):
        source_day = week_days_src[i]
        destination_day = week_start_dst + timedelta(days=i)
        rotations_src = db.query(CallRotation).filter(CallRotation.date == source_day).all()
        for rotation in rotations_src:
            if rotation.call_group_id is None:
                continue
            existing = db.query(CallRotation).filter(
                CallRotation.date == destination_day,
                CallRotation.call_group_id == rotation.call_group_id,
            ).first()
            if not existing:
                db.add(CallRotation(
                    surgeon_id=rotation.surgeon_id,
                    date=destination_day,
                    rotation_type="primary",
                    call_group_id=rotation.call_group_id,
                ))
                copied += 1
    db.commit()
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
    call_group_id_value = _parse_call_group_id(call_group_id)
    query = db.query(CallRotation).filter(CallRotation.date == assignment_date)
    if call_group_id_value is not None:
        query = query.filter(CallRotation.call_group_id == call_group_id_value)
    else:
        query = query.filter(CallRotation.call_group_id.is_(None))
    query.delete()
    db.commit()
    return RedirectResponse(f"/admin/call-schedule?{_call_schedule_qs(month_offset)}", status_code=303)
