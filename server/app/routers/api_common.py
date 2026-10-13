"""Shared helpers for API route modules."""
from datetime import date

from fastapi import HTTPException

# Native Calendar may page years of built call; keep a hard ceiling against abuse.
_MAX_NATIVE_RANGE_DAYS = 366 * 3


def parse_iso_date_range(start: str, end: str) -> tuple[date, date]:
    try:
        start_date = date.fromisoformat(start[:10])
        end_date = date.fromisoformat(end[:10])
    except ValueError as exc:
        raise HTTPException(400, "Invalid date range") from exc
    if end_date < start_date:
        raise HTTPException(400, "end must be on or after start")
    if (end_date - start_date).days > _MAX_NATIVE_RANGE_DAYS:
        raise HTTPException(400, f"Date range cannot exceed {_MAX_NATIVE_RANGE_DAYS} days")
    return start_date, end_date
