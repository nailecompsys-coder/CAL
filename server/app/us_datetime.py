"""US Eastern date/time display. Storage keys may stay ISO or YYYYMMDD; the portal does not."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

_EASTERN = ZoneInfo("America/New_York")
_COMPACT_BACKUP_TS = re.compile(r"^(\d{8})-(\d{6})$")


def coerce_datetime(value) -> datetime | None:
    """UTC datetime from compact backup stamps, ISO strings, or datetime objects."""
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    raw = str(value).strip()
    compact = _COMPACT_BACKUP_TS.match(raw)
    if compact:
        return datetime.strptime(compact.group(1) + compact.group(2), "%Y%m%d%H%M%S").replace(
            tzinfo=timezone.utc
        )
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def format_us_datetime(value) -> str:
    """M/D/YYYY h:mm AM/PM ET. Empty or unparseable values render as an em dash."""
    parsed = coerce_datetime(value)
    if not parsed:
        return "—"
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(_EASTERN).strftime("%-m/%-d/%Y %-I:%M %p ET")
