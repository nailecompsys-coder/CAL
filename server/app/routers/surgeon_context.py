"""Shared surgeon route context helpers."""
from fastapi import Request

from .. import __version__ as app_version
from ..auth import SURGEON_ADMIN_PREVIEW_DEVICE_NAME
from ..models import SurgeonDayItem
from ..practice_time import practice_today


def base_context(request: Request, surgeon, device=None, **kwargs):
    user_agent = request.headers.get("user-agent", "")
    desktop_preview = (
        device is not None
        and getattr(device, "device_name", None) == SURGEON_ADMIN_PREVIEW_DEVICE_NAME
    )
    desktop_browser = any(marker in user_agent for marker in ("Macintosh", "Windows", "Linux x86_64"))
    return {
        "request": request,
        "surgeon": surgeon,
        "today": practice_today(),
        "desktop_preview": desktop_preview,
        "desktop_browser": desktop_browser,
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
