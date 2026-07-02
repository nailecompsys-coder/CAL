"""Date and time helpers for native payloads."""

from datetime import date, time


def parse_hhmm(raw: str | None) -> time | None:
    if not raw:
        return None
    try:
        hour, minute = raw.split(":")[:2]
        return time(int(hour), int(minute))
    except Exception:
        return None


def fmt_time(value: time | None) -> str | None:
    return value.strftime("%H:%M") if value else None


def session_times(session: str | None) -> tuple[str, str]:
    if session == "am":
        return ("08:00", "12:00")
    if session == "pm":
        return ("13:00", "17:00")
    return ("08:00", "17:00")


def date_label(day: date) -> dict:
    return {
        "date": day.isoformat(),
        "dayName": day.strftime("%A"),
        "dayShort": day.strftime("%a"),
        "dayFull": day.strftime("%m-%d-%Y"),
    }
