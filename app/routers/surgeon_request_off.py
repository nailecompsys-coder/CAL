"""Surgeon time-off request routes."""
import calendar as _cal
import urllib.parse
from collections import defaultdict
from datetime import date, timedelta

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import func as sql_func
from sqlalchemy.orm import Session, joinedload

from ..auth import get_current_surgeon
from ..conflicts import check_conflicts
from ..database import get_db
from ..jinja_env import templates
from ..models import CallGroup, CallRotation, DayOff, Surgeon
from .surgeon_context import base_context

router = APIRouter(prefix="/surgeon")


def _cg_short(name: str) -> str:
    """'Winter Garden / Apopka / Minneola Hospital' -> 'WG', 'Altamonte Hospital' -> 'ALT'"""
    part = name.split('/')[0].strip()
    stop = {'hospital', 'clinic', 'center', 'medical', 'the', 'of', 'and', 'at', 'surgery'}
    words = [w for w in part.split() if w.lower() not in stop]
    if len(words) >= 2:
        return ''.join(w[0].upper() for w in words[:3])
    return words[0][:3].upper() if words else name[:3].upper()


def _dominant_cg_id(surgeon_id: int, sd: date, ed: date, db: Session):
    """Return the call_group_id the surgeon is assigned to most during sd-ed."""
    row = (
        db.query(CallRotation.call_group_id, sql_func.count(CallRotation.id).label('cnt'))
        .filter(
            CallRotation.surgeon_id == surgeon_id,
            CallRotation.date >= sd,
            CallRotation.date <= ed,
            CallRotation.call_group_id.isnot(None),
        )
        .group_by(CallRotation.call_group_id)
        .order_by(sql_func.count(CallRotation.id).desc())
        .first()
    )
    return row[0] if row else None


def _year_months(all_reqs) -> list[tuple[int, int]]:
    """Rolling 12-month window from the current month, extended for future requests beyond it."""
    today = date.today()
    months = []
    year = today.year
    month = today.month
    for offset in range(12):
        y = year + ((month - 1 + offset) // 12)
        m = ((month - 1 + offset) % 12) + 1
        months.append((y, m))
    seen = {(y, m) for y, m in months}
    for req in all_reqs:
        ym = (req.start_date.year, req.start_date.month)
        if ym not in seen and ym >= months[0]:
            months.append(ym)
            seen.add(ym)
    months.sort()
    return months


@router.get("/request-off", response_class=HTMLResponse)
def request_off_page(request: Request, db: Session = Depends(get_db), auth=Depends(get_current_surgeon)):
    surgeon, device = auth
    today = date.today()
    months = _year_months([])
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

    months = _year_months(all_requests)
    first_year, first_month = months[0]
    last_year, last_month = months[-1]
    display_range_label = f"{_cal.month_abbr[first_month]} {first_year} - {_cal.month_abbr[last_month]} {last_year}"
    is_physician = surgeon.staff_type == "physician"

    if is_physician:
        call_groups = db.query(CallGroup).order_by(CallGroup.sort_order, CallGroup.name).all()

        ph_reqs = [r for r in all_requests if r.surgeon.staff_type == "physician"]
        by_section: dict = defaultdict(list)
        for req in ph_reqs:
            cg_id = _dominant_cg_id(req.surgeon_id, req.start_date, req.end_date, db)
            by_section[(req.start_date.year, req.start_date.month, cg_id)].append(req)

        sections = []
        for y, m in months:
            for g in call_groups:
                reqs = by_section.get((y, m, g.id), [])
                sections.append({
                    "header": f"{_cal.month_abbr[m].upper()} {_cg_short(g.name)}",
                    "requests": reqs,
                })
    else:
        pa_reqs = [r for r in all_requests if r.surgeon.staff_type != "physician"]
        by_month: dict = defaultdict(list)
        for req in pa_reqs:
            by_month[(req.start_date.year, req.start_date.month)].append(req)

        sections = []
        for y, m in months:
            sections.append({
                "header": _cal.month_abbr[m].upper(),
                "requests": by_month.get((y, m), []),
            })

    return templates.TemplateResponse(
        "surgeon/request_off.html",
        base_context(
            request,
            surgeon,
            device=device,
            sections=sections,
            today=today,
            display_range_label=display_range_label,
        ),
    )


@router.post("/request-off")
def submit_request_off(
    start_date: str = Form(...),
    end_date: str = Form(...),
    reason: str = Form(""),
    notes: str = Form(""),
    db: Session = Depends(get_db),
    auth=Depends(get_current_surgeon),
):
    surgeon, _ = auth
    today = date.today()
    sd = date.fromisoformat(start_date)
    ed = date.fromisoformat(end_date)
    if sd < today or ed < today:
        warn = urllib.parse.quote("Days off can only be requested for today or later.")
        return RedirectResponse(f"/surgeon/request-off?open=1&warn={warn}", status_code=303)
    if ed < sd:
        warn = urllib.parse.quote("End date must be the same day or after the start date.")
        return RedirectResponse(f"/surgeon/request-off?open=1&warn={warn}", status_code=303)

    conflict_msgs = check_conflicts(
        surgeon.id,
        sd,
        ed,
        db,
        target_entity={"type": "day_off", "start_date": sd, "end_date": ed},
    )

    overlap = db.query(DayOff).filter(
        DayOff.surgeon_id == surgeon.id,
        DayOff.status.in_(["pending", "approved"]),
        DayOff.start_date <= ed,
        DayOff.end_date >= sd,
    ).first()
    if overlap:
        conflict_msgs.append(
            f"You already have a request for {overlap.start_date.strftime('%b %-d')}–{overlap.end_date.strftime('%b %-d')}"
        )

    warn_param = ""
    if conflict_msgs:
        warn_param = "&warn=" + urllib.parse.quote(" · ".join(conflict_msgs[:3]))

    d = DayOff(
        surgeon_id=surgeon.id,
        start_date=sd,
        end_date=ed,
        reason=reason,
        notes=notes,
        status="pending",
    )
    db.add(d)
    db.commit()
    return RedirectResponse(f"/surgeon/request-off?submitted=1{warn_param}", status_code=303)
