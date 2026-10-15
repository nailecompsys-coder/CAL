from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy.orm import Session

from .models import Surgeon


def save_native_surgery_notes(db: Session, surgeon: Surgeon, case_id: int, notes: str, send_push_fn) -> dict:
    del db, surgeon, case_id, notes, send_push_fn
    raise HTTPException(410, "Surgery notes are not kept on the schedule")
