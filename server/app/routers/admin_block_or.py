"""Admin Block OR workspace routes."""

from datetime import date, time, timedelta
from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session, joinedload

from ..admin_clinic_schedule_page_service import week_days_for_offset
from ..auth import get_current_admin
from ..database import get_db
from ..jinja_env import templates
from ..models import Location, ORBlockAssignment, ORBlockInstance, Surgeon, SurgicalCase
from ..or_block_service import (
    BlockORCreateInput,
    add_case_to_block,
    assign_block,
    block_workspace,
    candidate_surgeon_rows,
    clear_block_assignment,
    copy_or_block_capacity,
    create_or_blocks,
    delete_or_block_instance,
    parse_hhmm,
    remove_block_assignment,
    session_default_times,
    update_block_assignment,
    update_block_case,
    update_or_block_instance,
)
from ..surgeon_visibility import surgeon_is_visible
from .admin import _base, _sort_surgeons_physicians_first

router = APIRouter(prefix="/admin")


def _redirect(
    week_offset: int,
    msg: str = "",
    warn: str = "",
    block_id: int | None = None,
    panel: str = "",
    case_id: int | None = None,
) -> RedirectResponse:
    target = f"/admin/block-or?week_offset={week_offset}"
    if block_id:
        target += f"&block_id={block_id}"
    if case_id:
        target += f"&case_id={case_id}"
    if panel:
        target += f"&panel={quote(panel)}"
    if msg:
        target += f"&msg={quote(msg)}"
    if warn:
        target += f"&warn={quote(warn)}"
    return RedirectResponse(target, status_code=303)


def _parse_start_time(value: str, fallback: time) -> time:
    raw = (value or "").strip()
    if not raw:
        return fallback
    return parse_hhmm(raw, fallback)


@router.get("/block-or", response_class=HTMLResponse)
def block_or_page(
    request: Request,
    week_offset: int = 0,
    block_id: int | None = None,
    case_id: int | None = None,
    db: Session = Depends(get_db),
    admin=Depends(get_current_admin),
):
    today, week_days = week_days_for_offset(week_offset)
    workspace = block_workspace(db, week_days[0], week_days[-1])
    surgeons = [
        row for row in db.query(Surgeon).filter(
            Surgeon.is_active == True,  # noqa: E712
            Surgeon.staff_type == "physician",
        ).order_by(Surgeon.sort_order, Surgeon.last_name).all()
        if surgeon_is_visible(row)
    ]
    selected_block = None
    candidates = []
    assignments = []
    block_cases = []
    if block_id:
        selected_block = (
            db.query(ORBlockInstance)
            .options(
                joinedload(ORBlockInstance.location),
                joinedload(ORBlockInstance.assignments).joinedload(ORBlockAssignment.surgeon),
            )
            .filter(ORBlockInstance.id == block_id)
            .first()
        )
        if selected_block:
            candidates = candidate_surgeon_rows(db, selected_block)
            assignments = sorted(
                selected_block.assignments or [],
                key=lambda row: (row.start_time or selected_block.start_time, row.id),
            )
            block_cases = (
                db.query(SurgicalCase)
                .options(
                    joinedload(SurgicalCase.surgeon),
                    joinedload(SurgicalCase.location),
                )
                .filter(
                    SurgicalCase.or_block_instance_id == selected_block.id,
                    SurgicalCase.status != "cancelled",
                )
                .order_by(SurgicalCase.start_time, SurgicalCase.id)
                .all()
            )
    cases_by_surgeon: list[dict] = []
    editing_case = None
    if selected_block:
        from collections import defaultdict

        grouped: dict[int | None, list] = defaultdict(list)
        for case in block_cases:
            grouped[case.surgeon_id].append(case)
        seen: set[int | None] = set()
        for row in assignments:
            sid = row.surgeon_id
            seen.add(sid)
            cases_by_surgeon.append(
                {
                    "surgeon": row.surgeon,
                    "assignment": row,
                    "cases": grouped.get(sid, []),
                }
            )
        for sid, cases in grouped.items():
            if sid in seen:
                continue
            cases_by_surgeon.append(
                {
                    "surgeon": cases[0].surgeon if cases else None,
                    "assignment": None,
                    "cases": cases,
                }
            )
        if case_id:
            editing_case = next((row for row in block_cases if row.id == case_id), None)
    locations = (
        db.query(Location)
        .filter(Location.is_active == True, Location.location_type == "hospital")  # noqa: E712
        .order_by(Location.name)
        .all()
    )
    return templates.TemplateResponse("admin/block_or.html", _base(
        request,
        admin,
        db=db,
        today=today,
        week_days=week_days,
        week_offset=week_offset,
        locations=locations,
        workspace=workspace,
        surgeons=_sort_surgeons_physicians_first(surgeons),
        selected_block=selected_block,
        candidates=candidates,
        assignments=assignments,
        block_cases=block_cases,
        cases_by_surgeon=cases_by_surgeon,
        editing_case=editing_case,
        copy_default_end=week_days[0] + timedelta(days=364),
    ))


@router.post("/block-or/create")
def block_or_create(
    name: str = Form("Open Block"),
    start_date: str = Form(...),
    end_date: str = Form(...),
    weekdays: list[int] = Form(...),
    location_ids: list[int] = Form(...),
    session: str = Form("am"),
    start_time: str = Form(""),
    end_time: str = Form(""),
    room_text: str = Form(""),
    notes: str = Form(""),
    week_offset: int = Form(0),
    db: Session = Depends(get_db),
    admin=Depends(get_current_admin),
):
    try:
        default_start, default_end = session_default_times(session)
        payload = BlockORCreateInput(
            name=name,
            start_date=date.fromisoformat(start_date),
            end_date=date.fromisoformat(end_date),
            weekdays=weekdays,
            location_ids=location_ids,
            session=session,
            start_time=parse_hhmm(start_time, default_start),
            end_time=parse_hhmm(end_time, default_end),
            recurrence="weekly" if date.fromisoformat(start_date) != date.fromisoformat(end_date) else "once",
            notes=notes,
            room_text=room_text,
        )
        result = create_or_blocks(db, payload, admin.id)
    except ValueError as exc:
        return _redirect(week_offset, warn=str(exc))
    warn = ""
    if not (room_text or "").strip() and result.get("created"):
        warn = "Created without OR room — flagged for immediate follow-up."
    if result.get("created"):
        return _redirect(week_offset, msg=f"created:{result['created']}", warn=warn, panel="create")
    if result.get("updated"):
        return _redirect(week_offset, msg="updated", panel="create")
    return _redirect(week_offset, warn="No Block OR windows were saved.", panel="create")


@router.post("/block-or/copy")
def block_or_copy(
    weekdays: list[int] = Form(...),
    end_date: str = Form(...),
    location_id: str = Form(""),
    source_block_id: str = Form(""),
    week_offset: int = Form(0),
    db: Session = Depends(get_db),
    admin=Depends(get_current_admin),
):
    _, week_days = week_days_for_offset(week_offset)
    loc_raw = (location_id or "").strip()
    block_raw = (source_block_id or "").strip()
    try:
        result = copy_or_block_capacity(
            db,
            source_week_start=week_days[0],
            weekdays=weekdays,
            end_date=date.fromisoformat(end_date),
            location_id=int(loc_raw) if loc_raw.isdigit() else None,
            source_block_id=int(block_raw) if block_raw.isdigit() else None,
            admin_id=admin.id,
        )
    except ValueError as exc:
        return _redirect(
            week_offset,
            warn=str(exc),
            block_id=int(block_raw) if block_raw.isdigit() else None,
            panel="copy",
        )
    skipped = result.get("skipped") or []
    warn = " · ".join(skipped[:6])
    if len(skipped) > 6:
        warn += f" · +{len(skipped) - 6} more skipped"
    return _redirect(
        week_offset,
        msg=f"copied:{result['created']}",
        warn=warn,
        block_id=int(block_raw) if block_raw.isdigit() else None,
        panel="copy",
    )


@router.post("/block-or/{block_id:int}/edit")
def block_or_edit(
    block_id: int,
    location_id: int = Form(...),
    session: str = Form("am"),
    start_time: str = Form(...),
    end_time: str = Form(...),
    room_text: str = Form(""),
    notes: str = Form(""),
    week_offset: int = Form(0),
    db: Session = Depends(get_db),
    admin=Depends(get_current_admin),
):
    try:
        default_start, default_end = session_default_times(session)
        update_or_block_instance(
            db,
            block_id,
            location_id=location_id,
            session=session,
            start_time=parse_hhmm(start_time, default_start),
            end_time=parse_hhmm(end_time, default_end),
            notes=notes,
            room_text=room_text,
            admin_id=admin.id,
        )
    except ValueError as exc:
        return _redirect(week_offset, warn=str(exc), block_id=block_id, panel="edit")
    warn = ""
    if not (room_text or "").strip():
        warn = "Saved without OR room — flagged for immediate follow-up."
    return _redirect(week_offset, msg="updated", warn=warn, block_id=block_id, panel="edit")


@router.post("/block-or/{block_id:int}/assign")
def block_or_assign(
    block_id: int,
    surgeon_id: int = Form(...),
    start_time: str = Form(""),
    case_count: int = Form(1),
    assignment_note: str = Form(""),
    week_offset: int = Form(0),
    db: Session = Depends(get_db),
    admin=Depends(get_current_admin),
):
    block = db.get(ORBlockInstance, block_id)
    if not block:
        return _redirect(week_offset, warn="Block not found")
    try:
        _, warnings = assign_block(
            db,
            block_id,
            surgeon_id,
            admin.id,
            assigned_start_time=_parse_start_time(start_time, block.start_time),
            case_count=case_count,
            assignment_note=assignment_note,
        )
    except ValueError as exc:
        return _redirect(week_offset, warn=str(exc), block_id=block_id, panel="assign")
    warn = "; ".join(warnings[:3]) if warnings else ""
    return _redirect(week_offset, msg="assigned", warn=warn, block_id=block_id, panel="assign")


@router.post("/block-or/{block_id:int}/assignments/{assignment_id:int}/update")
def block_or_update_assignment(
    block_id: int,
    assignment_id: int,
    surgeon_id: int = Form(...),
    start_time: str = Form(""),
    case_count: int = Form(1),
    assignment_note: str = Form(""),
    week_offset: int = Form(0),
    db: Session = Depends(get_db),
    admin=Depends(get_current_admin),
):
    block = db.get(ORBlockInstance, block_id)
    if not block:
        return _redirect(week_offset, warn="Block not found")
    try:
        _, warnings = update_block_assignment(
            db,
            block_id,
            assignment_id,
            surgeon_id,
            admin.id,
            assigned_start_time=_parse_start_time(start_time, block.start_time),
            case_count=case_count,
            assignment_note=assignment_note,
        )
    except ValueError as exc:
        return _redirect(week_offset, warn=str(exc), block_id=block_id)
    warn = "; ".join(warnings[:3]) if warnings else ""
    return _redirect(week_offset, msg="assignment-updated", warn=warn, block_id=block_id)


@router.post("/block-or/{block_id:int}/assignments/{assignment_id:int}/remove")
def block_or_remove_assignment(
    block_id: int,
    assignment_id: int,
    week_offset: int = Form(0),
    db: Session = Depends(get_db),
    admin=Depends(get_current_admin),
):
    try:
        remove_block_assignment(db, block_id, assignment_id, admin_id=admin.id)
    except ValueError as exc:
        return _redirect(week_offset, warn=str(exc), block_id=block_id)
    return _redirect(week_offset, msg="assignment-removed", block_id=block_id)


@router.post("/block-or/{block_id:int}/clear")
def block_or_clear(
    block_id: int,
    week_offset: int = Form(0),
    db: Session = Depends(get_db),
    admin=Depends(get_current_admin),
):
    try:
        clear_block_assignment(db, block_id, admin_id=admin.id)
    except ValueError as exc:
        return _redirect(week_offset, warn=str(exc), block_id=block_id)
    return _redirect(week_offset, msg="cleared", block_id=block_id)


@router.post("/block-or/{block_id:int}/cases")
def block_or_add_case(
    block_id: int,
    surgeon_id: int = Form(...),
    start_time: str = Form(""),
    patient_name: str = Form(""),
    procedure: str = Form(""),
    week_offset: int = Form(0),
    db: Session = Depends(get_db),
    admin=Depends(get_current_admin),
):
    block = db.get(ORBlockInstance, block_id)
    if not block:
        return _redirect(week_offset, warn="Block not found")
    try:
        _, warnings = add_case_to_block(
            db,
            block_id,
            surgeon_id,
            _parse_start_time(start_time, block.start_time),
            procedure=procedure,
            patient_name=patient_name,
            admin_id=admin.id,
        )
    except ValueError as exc:
        return _redirect(week_offset, warn=str(exc), block_id=block_id, panel="assign")
    warn = "; ".join(warnings[:3]) if warnings else ""
    return _redirect(week_offset, msg="case-added", warn=warn, block_id=block_id)


@router.post("/block-or/{block_id:int}/cases/{case_id:int}/update")
def block_or_update_case(
    block_id: int,
    case_id: int,
    surgeon_id: int = Form(...),
    start_time: str = Form(""),
    patient_name: str = Form(""),
    procedure: str = Form(""),
    week_offset: int = Form(0),
    db: Session = Depends(get_db),
    admin=Depends(get_current_admin),
):
    block = db.get(ORBlockInstance, block_id)
    if not block:
        return _redirect(week_offset, warn="Block not found")
    try:
        _, warnings = update_block_case(
            db,
            block_id,
            case_id,
            start_time=_parse_start_time(start_time, block.start_time),
            procedure=procedure,
            patient_name=patient_name,
            surgeon_id=surgeon_id,
            admin_id=admin.id,
        )
    except ValueError as exc:
        return _redirect(
            week_offset,
            warn=str(exc),
            block_id=block_id,
            panel="case",
            case_id=case_id,
        )
    warn = "; ".join(warnings[:3]) if warnings else ""
    return _redirect(week_offset, msg="case-updated", warn=warn, block_id=block_id)


@router.post("/block-or/{block_id:int}/delete")
def block_or_delete(
    block_id: int,
    week_offset: int = Form(0),
    db: Session = Depends(get_db),
    admin=Depends(get_current_admin),
):
    try:
        delete_or_block_instance(db, block_id, admin_id=admin.id)
    except ValueError as exc:
        return _redirect(week_offset, warn=str(exc), block_id=block_id, panel="remove")
    return _redirect(week_offset, msg="deleted", panel="create")
