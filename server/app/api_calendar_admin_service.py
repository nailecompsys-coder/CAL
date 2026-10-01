"""Compatibility entry point for the database-owned master calendar feed."""
from sqlalchemy.orm import Session

from .master_calendar_service import build_master_calendar_events


def build_admin_calendar_events(db: Session, start_date, end_date, surgeon_id: int | None = None) -> list[dict]:
    return build_master_calendar_events(db, start_date, end_date, surgeon_id)
