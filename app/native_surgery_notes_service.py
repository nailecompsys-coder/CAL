from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy.orm import Session

from .models import Surgeon, SurgicalCase


def save_native_surgery_notes(db: Session, surgeon: Surgeon, case_id: int, notes: str, send_push_fn) -> dict:
    row = db.get(SurgicalCase, case_id)
    if not row or row.surgeon_id != surgeon.id:
        raise HTTPException(404, "Case not found")
    row.surgeon_notes = notes.strip() or None
    db.commit()
    send_push_fn(
        surgeon.id,
        "Surgical case notes updated",
        f"{row.date.strftime('%b %-d')} case notes saved",
        db,
        {"type": "surgical_case", "caseId": row.id},
    )
    return {"ok": True}
