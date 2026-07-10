"""Business logic for native on-call coverage swaps."""
from datetime import UTC, datetime

from fastapi import HTTPException
from sqlalchemy.orm import Session, joinedload

from .conflicts import check_conflicts_structured
from .models import CallCoverage, CallRotation, Surgeon
from .native_support import serialize_call_assignment
from .or_block_service import log_schedule_change
from .push import notify_admins, send_native_push_to_surgeon
from .scheduling_gate_service import clip_window_to_now, practice_today
from .surgeon_visibility import surgeon_is_visible


def assign_native_call_coverage(
    db: Session,
    requesting_surgeon: Surgeon,
    rotation_id: int,
    covering_surgeon_id: int | None = None,
    notes: str = "",
) -> dict:
    rotation = _call_rotation_for_response(db, rotation_id)
    if not rotation:
        raise HTTPException(404, "Call assignment not found")

    if rotation.date < practice_today():
        raise HTTPException(400, "Call coverage can only be set for today or later.")

    covering_id = covering_surgeon_id or requesting_surgeon.id
    covering = db.get(Surgeon, covering_id)
    if not surgeon_is_visible(covering):
        raise HTTPException(400, "Covering surgeon is not active")

    original_staff_type = rotation.surgeon.staff_type if rotation.surgeon else requesting_surgeon.staff_type
    if covering.staff_type != original_staff_type:
        role = "surgeon" if original_staff_type == "physician" else "PA/staff"
        raise HTTPException(400, f"Coverage must be assigned to another {role}.")

    existing = db.query(CallCoverage).filter(
        CallCoverage.call_rotation_id == rotation.id,
        CallCoverage.status == "active",
    ).first()
    if existing:
        existing.status = "canceled"
        existing.canceled_at = _utc_now()

    warnings = _coverage_swap_warnings(db, rotation, covering)

    coverage = CallCoverage(
        call_rotation_id=rotation.id,
        original_surgeon_id=rotation.surgeon_id,
        covering_surgeon_id=covering.id,
        requested_by_surgeon_id=requesting_surgeon.id,
        notes=notes.strip() or None,
        status="active",
    )
    db.add(coverage)
    db.commit()
    db.refresh(coverage)
    log_schedule_change(
        db,
        event_type="call_coverage_updated",
        surgeon_id=covering.id,
        event_date=rotation.date,
        title="Call coverage updated",
        body=f"{covering.initials} covering {rotation.call_group.name if rotation.call_group else 'call'} on {rotation.date.strftime('%b %-d')}",
        payload={"warnings": warnings} if warnings else None,
    )
    db.commit()

    if warnings:
        notify_admins(
            "Call coverage schedule conflict",
            f"{covering.full_name} covering {rotation.date.strftime('%b %-d')}: " + " · ".join(warnings[:3]),
            db,
            kind="call_coverage_conflict",
            payload={"rotationId": rotation.id, "coveringSurgeonId": covering.id, "warnings": warnings[:5]},
            require_schedule_opt_in=True,
        )

    if rotation.surgeon_id:
        send_native_push_to_surgeon(
            rotation.surgeon_id,
            "On-call coverage updated",
            f"{covering.initials} is covering {rotation.date.strftime('%b %-d')}",
            db,
            {"type": "call_coverage", "rotationId": rotation.id},
        )
    cover_body = f"You are covering {rotation.call_group.name if rotation.call_group else 'call'} on {rotation.date.strftime('%b %-d')}"
    if warnings:
        cover_body += " — schedule conflict noted; confirm with Shannon if needed."
    send_native_push_to_surgeon(
        covering.id,
        "On-call coverage assigned",
        cover_body,
        db,
        {"type": "call_coverage", "rotationId": rotation.id},
    )

    rotation = _call_rotation_for_response(db, rotation.id)
    result = serialize_call_assignment(rotation, requesting_surgeon.id)
    if warnings:
        result["warnings"] = warnings[:4]
    return result


def cancel_native_call_coverage(db: Session, requesting_surgeon: Surgeon, coverage_id: int) -> dict:
    coverage = db.get(CallCoverage, coverage_id)
    if not coverage or coverage.status != "active":
        raise HTTPException(404, "Coverage not found")

    coverage.status = "canceled"
    coverage.canceled_at = _utc_now()
    log_schedule_change(
        db,
        event_type="call_coverage_canceled",
        surgeon_id=coverage.covering_surgeon_id,
        event_date=coverage.rotation.date if coverage.rotation else None,
        title="Call coverage canceled",
        body="Coverage swap canceled",
    )
    db.commit()

    rotation = _call_rotation_for_response(db, coverage.call_rotation_id)
    return serialize_call_assignment(rotation, requesting_surgeon.id)


def _coverage_swap_warnings(db: Session, rotation: CallRotation, covering: Surgeon) -> list[str]:
    """Check covering surgeon against the rules engine for that call day."""
    clipped = clip_window_to_now(rotation.date, rotation.date)
    if clipped is None:
        return []
    target = {
        "type": "call_coverage",
        "date": rotation.date,
        "start_date": rotation.date,
        "end_date": rotation.date,
    }
    warnings: list[str] = []
    for conflict in check_conflicts_structured(
        covering.id,
        rotation.date,
        rotation.date,
        db,
        exclude_entity=("call_rotation", rotation.id),
        target_entity=target,
    ):
        warnings.append(f"{covering.initials}: {conflict.message}")
    return warnings


def _call_rotation_for_response(db: Session, rotation_id: int) -> CallRotation | None:
    return db.query(CallRotation).options(
        joinedload(CallRotation.surgeon),
        joinedload(CallRotation.call_group),
        joinedload(CallRotation.coverages).joinedload(CallCoverage.covering_surgeon),
    ).filter(CallRotation.id == rotation_id).first()


def _utc_now() -> datetime:
    return datetime.now(UTC)
