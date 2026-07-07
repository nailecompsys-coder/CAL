"""Services for surgeon-facing time-off requests."""

import calendar as calendar_lib
import urllib.parse
from collections import defaultdict
from datetime import date, timedelta

from sqlalchemy import func as sql_func
from sqlalchemy.orm import Session, joinedload

from .models import CallGroup, CallRotation, DayOff, Surgeon
from .push import notify_admins
from .scheduling_guardrails_service import dayoff_surgeon_warning, store_dayoff_findings
from .surgeon_visibility import surgeon_is_visible


def call_group_short(name: str) -> str:
    part = name.split('/')[0].strip()
    stop = {'hospital', 'clinic', 'center', 'medical', 'the', 'of', 'and', 'at', 'surgery'}
    words = [w for w in part.split() if w.lower() not in stop]
    if len(words) >= 2:
        return ''.join(w[0].upper() for w in words[:3])
    return words[0][:3].upper() if words else name[:3].upper()


def dominant_call_group_id(db: Session, surgeon_id: int, start_date: date, end_date: date):
    row = (
        db.query(CallRotation.call_group_id, sql_func.count(CallRotation.id).label('cnt'))
        .filter(
            CallRotation.surgeon_id == surgeon_id,
            CallRotation.date >= start_date,
            CallRotation.date <= end_date,
            CallRotation.call_group_id.isnot(None),
        )
        .group_by(CallRotation.call_group_id)
        .order_by(sql_func.count(CallRotation.id).desc())
        .first()
    )
    return row[0] if row else None


def year_months(all_requests) -> list[tuple[int, int]]:
    today = date.today()
    months = []
    year = today.year
    month = today.month
    for offset in range(12):
        y = year + ((month - 1 + offset) // 12)
        m = ((month - 1 + offset) % 12) + 1
        months.append((y, m))
    seen = {(y, m) for y, m in months}
    for req in all_requests:
        ym = (req.start_date.year, req.start_date.month)
        if ym not in seen and ym >= months[0]:
            months.append(ym)
            seen.add(ym)
    months.sort()
    return months


def request_off_page_data(db: Session, surgeon: Surgeon) -> dict:
    today = date.today()
    months = year_months([])
    window_start = date(months[0][0], months[0][1], 1)
    discovery_end = today + timedelta(days=730)

    all_requests = (
        db.query(DayOff)
        .join(Surgeon, DayOff.surgeon_id == Surgeon.id)
        .filter(
            DayOff.status != "denied",
            Surgeon.is_active == True,
            DayOff.start_date <= discovery_end,
            DayOff.end_date >= window_start,
        )
        .order_by(DayOff.start_date)
        .options(joinedload(DayOff.surgeon))
        .all()
    )
    all_requests = [request for request in all_requests if surgeon_is_visible(request.surgeon)]

    months = year_months(all_requests)
    first_year, first_month = months[0]
    last_year, last_month = months[-1]
    display_range_label = f"{calendar_lib.month_abbr[first_month]} {first_year} - {calendar_lib.month_abbr[last_month]} {last_year}"

    if surgeon.staff_type == "physician":
        sections = physician_sections(db, months, all_requests)
    else:
        sections = staff_sections(months, all_requests)

    return {
        "today": today,
        "sections": sections,
        "display_range_label": display_range_label,
    }


def physician_sections(db: Session, months: list[tuple[int, int]], all_requests: list[DayOff]) -> list[dict]:
    call_groups = db.query(CallGroup).order_by(CallGroup.sort_order, CallGroup.name).all()
    physician_requests = [request for request in all_requests if surgeon_is_visible(request.surgeon) and request.surgeon.staff_type == "physician"]
    by_section: dict = defaultdict(list)
    for request in physician_requests:
        cg_id = dominant_call_group_id(db, request.surgeon_id, request.start_date, request.end_date)
        by_section[(request.start_date.year, request.start_date.month, cg_id)].append(request)

    sections = []
    for year, month in months:
        for group in call_groups:
            sections.append({
                "header": f"{calendar_lib.month_abbr[month].upper()} {call_group_short(group.name)}",
                "requests": by_section.get((year, month, group.id), []),
            })
    return sections


def staff_sections(months: list[tuple[int, int]], all_requests: list[DayOff]) -> list[dict]:
    staff_requests = [request for request in all_requests if surgeon_is_visible(request.surgeon) and request.surgeon.staff_type != "physician"]
    by_month: dict = defaultdict(list)
    for request in staff_requests:
        by_month[(request.start_date.year, request.start_date.month)].append(request)

    return [
        {
            "header": calendar_lib.month_abbr[month].upper(),
            "requests": by_month.get((year, month), []),
        }
        for year, month in months
    ]


def submit_request_off(db: Session, surgeon: Surgeon, start_date: str, end_date: str, reason: str, notes: str) -> dict:
    today = date.today()
    start = date.fromisoformat(start_date)
    end = date.fromisoformat(end_date)
    if start < today or end < today:
        return {"ok": False, "warn": "Days off can only be requested for today or later."}
    if end < start:
        return {"ok": False, "warn": "End date must be the same day or after the start date."}

    conflict_msgs = []
    overlap = db.query(DayOff).filter(
        DayOff.surgeon_id == surgeon.id,
        DayOff.status.in_(["pending", "approved"]),
        DayOff.start_date <= end,
        DayOff.end_date >= start,
    ).first()
    if overlap:
        conflict_msgs.append(
            f"You already have a request for {overlap.start_date.strftime('%b %-d')}–{overlap.end_date.strftime('%b %-d')}"
        )

    dayoff = DayOff(
        surgeon_id=surgeon.id,
        start_date=start,
        end_date=end,
        reason=reason,
        notes=notes,
        status="pending",
    )
    db.add(dayoff)
    db.commit()
    db.refresh(dayoff)
    findings = store_dayoff_findings(db, dayoff)
    if findings:
        conflict_msgs.append(dayoff_surgeon_warning(findings))
    notify_admins(
        "CAL request pending",
        f"{surgeon.full_name} requested {start.strftime('%b %-d')} to {end.strftime('%b %-d')}.",
        db,
        kind="day_off_request",
        payload={"dayOffId": dayoff.id, "surgeonId": surgeon.id},
        require_dayoff_opt_in=True,
    )
    warn_param = ""
    if conflict_msgs:
        warn_param = "&warn=" + urllib.parse.quote(" · ".join(conflict_msgs[:3]))
    return {"ok": True, "warn_param": warn_param}
