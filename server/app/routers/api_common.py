"""Shared helpers for API route modules."""
from datetime import date

from fastapi import HTTPException


def parse_iso_date_range(start: str, end: str) -> tuple[date, date]:
    try:
        return date.fromisoformat(start[:10]), date.fromisoformat(end[:10])
    except ValueError as exc:
        raise HTTPException(400, "Invalid date range") from exc
