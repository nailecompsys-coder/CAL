from __future__ import annotations

from sqlalchemy.orm import Session

from .models import Availability, Surgeon
from .native_support import parse_hhmm


def save_native_availability(db: Session, surgeon: Surgeon, days: list, check_conflicts_fn) -> dict:
    warnings = []
    for row in days:
        existing = db.query(Availability).filter(
            Availability.surgeon_id == surgeon.id,
            Availability.date == row.date,
        ).first()
        if not row.isAvailable:
            warnings.extend(check_conflicts_fn(
                surgeon.id,
                row.date,
                row.date,
                db,
                target_entity={"type": "availability", "date": row.date},
            ))
        if existing:
            existing.is_available = row.isAvailable
            existing.start_time = parse_hhmm(row.start)
            existing.end_time = parse_hhmm(row.end)
        else:
            db.add(Availability(
                surgeon_id=surgeon.id,
                date=row.date,
                is_available=row.isAvailable,
                start_time=parse_hhmm(row.start),
                end_time=parse_hhmm(row.end),
            ))
    db.commit()
    return {"ok": True, "warnings": warnings[:5]}
