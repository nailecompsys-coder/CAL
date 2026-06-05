"""Shared surgeon route context helpers."""
from datetime import date

from fastapi import Request

from .. import __version__ as app_version
from ..auth import SURGEON_ADMIN_PREVIEW_DEVICE_NAME
from ..models import SurgeonDayItem


def base_context(request: Request, surgeon, device=None, **kwargs):
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


def serialize_personal_item(pi: SurgeonDayItem) -> dict:
    return {
        "id": pi.id,
        "title": pi.title,
        "notes": (pi.notes or "").strip(),
        "start": pi.start_time.strftime("%H:%M") if pi.start_time else None,
        "end": pi.end_time.strftime("%H:%M") if pi.end_time else None,
        "sortOrder": pi.sort_order or 0,
    }
