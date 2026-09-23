"""Maintain effective daily call assignments as normalized relational rows."""

from sqlalchemy.orm import Session

from .models import CallCoverage, CallDailyAssignment, CallGroupLocation, CallRotation


def sync_call_rotation(db: Session, rotation: CallRotation) -> int:
    db.flush()
    db.query(CallDailyAssignment).filter(
        CallDailyAssignment.call_rotation_id == rotation.id,
    ).delete(synchronize_session=False)
    if not rotation.call_group_id or not rotation.surgeon_id:
        return 0
    active_coverage = (
        db.query(CallCoverage)
        .filter(
            CallCoverage.call_rotation_id == rotation.id,
            CallCoverage.status == "active",
        )
        .order_by(CallCoverage.id.desc())
        .first()
    )
    surgeon_id = active_coverage.covering_surgeon_id if active_coverage else rotation.surgeon_id
    location_ids = [
        location_id for (location_id,) in db.query(CallGroupLocation.location_id).filter(
            CallGroupLocation.call_group_id == rotation.call_group_id,
        ).all()
    ]
    for location_id in location_ids:
        existing = db.query(CallDailyAssignment).filter(
            CallDailyAssignment.date == rotation.date,
            CallDailyAssignment.location_id == location_id,
        ).one_or_none()
        if existing and existing.call_rotation_id != rotation.id:
            raise ValueError(
                f"Call location {location_id} already has an assignment on {rotation.date.isoformat()}."
            )
        db.add(CallDailyAssignment(
            date=rotation.date,
            location_id=location_id,
            surgeon_id=surgeon_id,
            call_group_id=rotation.call_group_id,
            call_rotation_id=rotation.id,
            call_coverage_id=active_coverage.id if active_coverage else None,
            original_surgeon_id=rotation.surgeon_id,
        ))
    db.flush()
    return len(location_ids)


def backfill_call_daily_assignments(db: Session) -> int:
    total = 0
    for rotation in db.query(CallRotation).order_by(CallRotation.date, CallRotation.id).all():
        total += sync_call_rotation(db, rotation)
    db.commit()
    return total
