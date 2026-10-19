"""One Jinja2 environment for all routers — custom filters register here only."""
import json as _json
import re as _re
from datetime import timezone as _timezone
from urllib.parse import quote as _url_quote
from zoneinfo import ZoneInfo as _ZoneInfo

import markupsafe
from fastapi.templating import Jinja2Templates

from .admin_notification_href import admin_notification_href
from .admin_notification_ack import notification_is_informational
from .device_names import readable_device_name
from .or_block_service import sanitize_schedule_note_for_humans
from .paths import TEMPLATES_DIR
from .us_datetime import format_us_datetime, format_usa_date
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


def _tojson(value):
    """JSON for a <script> block or a quoted attribute.

    A plain json.dumps string gets HTML-escaped, so quotes become &#34;
    inside <script> and the Meetings page script never runs. Markup keeps
    the quotes, and the replacements keep <script> and apostrophes from
    breaking out of the page.
    """
    raw = _json.dumps(value, separators=(",", ":"), default=str)
    return markupsafe.Markup(
        raw.replace("&", "\\u0026")
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("'", "\\u0027")
        .replace("\u2028", "\\u2028")
        .replace("\u2029", "\\u2029")
    )


templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
templates.env.filters["from_json"] = _json.loads
templates.env.filters["tojson"] = _tojson
templates.env.filters["urlquote"] = lambda s: _url_quote(str(s or ""), safe="")
templates.env.filters["eastern_time"] = _eastern_time
templates.env.filters["us_datetime"] = format_us_datetime
templates.env.filters["usa_date"] = format_usa_date
templates.env.filters["phone"] = _format_phone
templates.env.filters["bytes"] = _format_bytes
templates.env.filters["device_name"] = readable_device_name
templates.env.filters["release_label"] = release_label
templates.env.filters["release_channel"] = release_channel
templates.env.filters["human_schedule_note"] = sanitize_schedule_note_for_humans
templates.env.globals["admin_notification_href"] = admin_notification_href
templates.env.globals["notification_is_informational"] = notification_is_informational
