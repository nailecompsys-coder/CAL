"""One Jinja2 environment for all routers — custom filters register here only."""
import json as _json
from urllib.parse import quote as _url_quote

from fastapi.templating import Jinja2Templates

templates = Jinja2Templates(directory="app/templates")
templates.env.filters["from_json"] = _json.loads
templates.env.filters["urlquote"] = lambda s: _url_quote(str(s or ""), safe="")
