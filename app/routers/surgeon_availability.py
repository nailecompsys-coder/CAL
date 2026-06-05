"""Surgeon availability routes."""
import urllib.parse
from datetime import date, time as time_type, timedelta

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from ..auth import get_current_surgeon
from ..conflicts import check_conflicts
from ..database import get_db
from ..jinja_env import templates
from ..models import Availability
from .surgeon import _base

router = APIRouter(prefix="/surgeon")


@router.get("/availability", response_class=HTMLResponse)
def availability_page(request: Request, db: Session = Depends(get_db), auth=Depends(get_current_surgeon)):
    surgeon, device = auth
    today = date.today()
    avail_records = db.query(Availability).filter(
        Availability.surgeon_id == surgeon.id,
        Availability.date >= today,
        Availability.date <= today + timedelta(days=28),
    ).order_by(Availability.date).all()
    avail_map = {a.date: a for a in avail_records}

    days = []
    for i in range(28):
        d = today + timedelta(days=i)
        rec = avail_map.get(d)
        days.append({
            "date": d,
            "is_available": rec.is_available if rec else True,
            "start_time": rec.start_time if rec else None,
            "end_time": rec.end_time if rec else None,
        })

    weeks = [days[i:i+7] for i in range(0, len(days), 7)]
    return templates.TemplateResponse("surgeon/availability.html", _base(request, surgeon, device=device, weeks=weeks))


@router.post("/availability/save")
async def save_availability(
    request: Request,
    db: Session = Depends(get_db),
    auth=Depends(get_current_surgeon),
):
    surgeon, _ = auth
    today = date.today()
    form = await request.form()

    def parse_time(s: str):
        if not s:
            return None
        try:
            parts = s.strip().split(":")
            return time_type(int(parts[0]), int(parts[1]))
        except Exception:
            return None

    conflict_warnings = []

    for i in range(28):
        d = today + timedelta(days=i)
        date_str = d.isoformat()
        is_avail = form.get(f"avail_{date_str}") == "1"
        start_t = parse_time(form.get(f"start_{date_str}", ""))
        end_t = parse_time(form.get(f"end_{date_str}", ""))

        if not is_avail:
            conflicts = check_conflicts(
                surgeon.id,
                d,
                d,
                db,
                target_entity={"type": "availability", "date": d},
            )
            for msg in conflicts:
                conflict_warnings.append(f"{d.strftime('%b %-d')}: {msg}")

        existing = db.query(Availability).filter(
            Availability.surgeon_id == surgeon.id,
            Availability.date == d,
        ).first()
        if existing:
            existing.is_available = is_avail
            existing.start_time = start_t
            existing.end_time = end_t
        else:
            db.add(
                Availability(
                    surgeon_id=surgeon.id,
                    date=d,
                    is_available=is_avail,
                    start_time=start_t,
                    end_time=end_t,
                )
            )

    db.commit()

    if conflict_warnings:
        warn = urllib.parse.quote(" · ".join(conflict_warnings[:5]))
        return RedirectResponse(f"/surgeon/availability?saved=1&warn={warn}", status_code=303)
    return RedirectResponse("/surgeon/availability?saved=1", status_code=303)
