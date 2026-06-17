"""Admin operations metrics routes."""

from datetime import date

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from ..admin_metrics_service import build_admin_metrics, default_metrics_range
from ..auth import get_current_admin
from ..database import get_db
from ..jinja_env import templates
from .admin import _base

router = APIRouter(prefix="/admin")


@router.get("/metrics", response_class=HTMLResponse)
def metrics_page(
    request: Request,
    start: str | None = None,
    end: str | None = None,
    staff_type: str = "physician",
    db: Session = Depends(get_db),
    admin=Depends(get_current_admin),
):
    default_start, default_end = default_metrics_range(date.today())
    start_date = _parse_date(start, default_start)
    end_date = _parse_date(end, default_end)
    if end_date < start_date:
        start_date, end_date = end_date, start_date

    metrics = build_admin_metrics(db, start_date, end_date, staff_type)
    return templates.TemplateResponse("admin/metrics.html", _base(
        request,
        admin,
        db=db,
        metrics=metrics,
        selected_staff_type=metrics["staff_type"],
    ))


def _parse_date(value: str | None, fallback: date) -> date:
    if not value:
        return fallback
    try:
        return date.fromisoformat(value)
    except ValueError:
        return fallback
