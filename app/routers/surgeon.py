"""Surgeon PWA HTML routes."""
from datetime import date

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from .. import __version__ as app_version
from ..jinja_env import templates
from ..auth import SURGEON_ADMIN_PREVIEW_DEVICE_NAME
from ..models import (
    SurgeonDayItem,
)

router = APIRouter(prefix="/surgeon")

def _base(request: Request, surgeon, device=None, **kwargs):
    desktop_preview = (
        device is not None
        and getattr(device, "device_name", None) == SURGEON_ADMIN_PREVIEW_DEVICE_NAME
    )
    return {
        "request": request,
        "surgeon": surgeon,
        "today": date.today(),
        "desktop_preview": desktop_preview,
        "app_version": app_version,
        **kwargs,
    }


def _serialize_personal(pi: SurgeonDayItem) -> dict:
    return {
        "id": pi.id,
        "title": pi.title,
        "notes": (pi.notes or "").strip(),
        "start": pi.start_time.strftime("%H:%M") if pi.start_time else None,
        "end": pi.end_time.strftime("%H:%M") if pi.end_time else None,
        "sortOrder": pi.sort_order or 0,
    }


@router.get("/register", response_class=HTMLResponse)
def register_page(request: Request, token: str = ""):
    return templates.TemplateResponse(
        "surgeon/register.html",
        {"request": request, "token": token, "app_version": app_version},
    )
