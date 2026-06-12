"""One Jinja2 environment for all routers — custom filters register here only."""
import json as _json
from datetime import timezone as _timezone
from urllib.parse import quote as _url_quote
from zoneinfo import ZoneInfo as _ZoneInfo

from fastapi.templating import Jinja2Templates


_EASTERN = _ZoneInfo("America/New_York")


def _eastern_time(value, fmt: str = "%b %d %I:%M %p %Z") -> str:
    if not value:
        return "—"
    if value.tzinfo is None:
        value = value.replace(tzinfo=_timezone.utc)
    return value.astimezone(_EASTERN).strftime(fmt).replace(" 0", " ")


templates = Jinja2Templates(directory="app/templates")
templates.env.filters["from_json"] = _json.loads
templates.env.filters["urlquote"] = lambda s: _url_quote(str(s or ""), safe="")
templates.env.filters["eastern_time"] = _eastern_time
