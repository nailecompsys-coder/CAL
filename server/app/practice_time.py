"""Practice-local clock. Schedule 'today' is America/New_York, never UTC date.today()."""

from datetime import date, datetime
from zoneinfo import ZoneInfo

PRACTICE_TZ = ZoneInfo("America/New_York")


def practice_now() -> datetime:
    return datetime.now(PRACTICE_TZ)


def practice_today() -> date:
    return practice_now().date()
