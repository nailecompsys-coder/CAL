"""One Jinja2 environment for all routers — custom filters register here only."""
import json as _json
import re as _re
from datetime import timezone as _timezone
from urllib.parse import quote as _url_quote
from zoneinfo import ZoneInfo as _ZoneInfo

from fastapi.templating import Jinja2Templates

from .device_names import readable_device_name
from .or_block_service import sanitize_schedule_note_for_humans
from .paths import TEMPLATES_DIR
from .version_display import release_channel, release_label


_EASTERN = _ZoneInfo("America/New_York")


def _eastern_time(value, fmt: str = "%b %d %I:%M %p %Z") -> str:
    if not value:
        return "—"
    if value.tzinfo is None:
        value = value.replace(tzinfo=_timezone.utc)
    return value.astimezone(_EASTERN).strftime(fmt).replace(" 0", " ")


def _format_phone(value) -> str:
    raw = str(value or "").strip()
    if not raw:
        return "—"
    digits = _re.sub(r"\D+", "", raw)
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    if len(digits) == 10:
        return f"({digits[:3]}) {digits[3:6]}-{digits[6:]}"
    return raw


def _format_bytes(value) -> str:
    try:
        size = float(value or 0)
    except (TypeError, ValueError):
        return "—"
    units = ["B", "KB", "MB", "GB", "TB"]
    unit = units[0]
    for unit in units:
        if size < 1024 or unit == units[-1]:
            break
        size /= 1024
    if unit == "B":
        return f"{int(size)} {unit}"
    return f"{size:.1f} {unit}"


templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
templates.env.filters["from_json"] = _json.loads
templates.env.filters["urlquote"] = lambda s: _url_quote(str(s or ""), safe="")
templates.env.filters["eastern_time"] = _eastern_time
templates.env.filters["phone"] = _format_phone
templates.env.filters["bytes"] = _format_bytes
templates.env.filters["device_name"] = readable_device_name
templates.env.filters["release_label"] = release_label
templates.env.filters["release_channel"] = release_channel
templates.env.filters["human_schedule_note"] = sanitize_schedule_note_for_humans
