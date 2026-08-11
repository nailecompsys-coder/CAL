from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy.orm import Session, joinedload

from .call_schedule_audit_service import actor_label_for_admin, log_call_schedule_change
from .conflicts import check_conflicts
from .models import AdminUser, CallGroup, CallRotation, Surgeon
from .push import send_push_to_surgeon


def rotation_query_for_assignment(db: Session, assignment_date: date, call_group_id: int | None):
    query = db.query(CallRotation).filter(CallRotation.date == assignment_date)
    if call_group_id is not None:
        return query.filter(CallRotation.call_group_id == call_group_id)
    return query.filter(CallRotation.call_group_id.is_(None))


def _group_name(db: Session, call_group_id: int | None) -> str | None:
    if call_group_id is None:
        return None
    group = db.get(CallGroup, call_group_id)
    return group.name if group else None


def assign_rotation(
    db: Session,
    assignment_date: date,
    surgeon_id: int | None,
    call_group_id: int | None,
    *,
    admin: AdminUser | None = None,
) -> list[str]:
    existing = rotation_query_for_assignment(db, assignment_date, call_group_id).first()
    from_surgeon_id = existing.surgeon_id if existing else None
    if existing:
        existing.surgeon_id = surgeon_id
        rotation_id = existing.id
    else:
        rotation = CallRotation(
            surgeon_id=surgeon_id,
            date=assignment_date,
            rotation_type="primary",
            call_group_id=call_group_id,
        )
        db.add(rotation)
        db.flush()
        rotation_id = rotation.id

    if from_surgeon_id != surgeon_id:
        log_call_schedule_change(
            db,
            action="assign" if surgeon_id else "clear",
            event_date=assignment_date,
            source="portal",
            call_group_id=call_group_id,
            call_group_name=_group_name(db, call_group_id),
            rotation_id=rotation_id,
            from_surgeon_id=from_surgeon_id,
            to_surgeon_id=surgeon_id,
            actor_admin_id=admin.id if admin else None,
            actor_label=actor_label_for_admin(admin),
        )
    db.commit()

    surgeon = db.get(Surgeon, surgeon_id) if surgeon_id else None
    if surgeon:
        send_push_to_surgeon(
            surgeon_id,
            "Schedule Update",
            f"You've been assigned on-call on {assignment_date.strftime('%b %d')}",
            db,
        )

    if not surgeon or not surgeon_id:
        return []
    conflicts = check_conflicts(
        surgeon_id,
        assignment_date,
        assignment_date,
        db,
        exclude_call_rotation_id=rotation_id,
        target_entity={"type": "call_rotation", "date": assignment_date},
    )
    return [f"{surgeon.full_name}: " + conflict for conflict in conflicts]


def copy_call_week(db: Session, source_offset: int) -> int:
    today = date.today()
    week_start = today - timedelta(days=today.weekday()) + timedelta(weeks=source_offset)
    week_days_src = [week_start + timedelta(days=i) for i in range(7)]
    week_start_dst = week_start + timedelta(weeks=1)
    copied = 0
    for i in range(7):
        source_day = week_days_src[i]
        destination_day = week_start_dst + timedelta(days=i)
        rotations_src = db.query(CallRotation).filter(CallRotation.date == source_day).all()
        for rotation in rotations_src:
            if rotation.call_group_id is None:
                continue
            existing = db.query(CallRotation).filter(
                CallRotation.date == destination_day,
                CallRotation.call_group_id == rotation.call_group_id,
            ).first()
            if not existing:
                db.add(CallRotation(
                    surgeon_id=rotation.surgeon_id,
                    date=destination_day,
                    rotation_type="primary",
                    call_group_id=rotation.call_group_id,
                ))
                copied += 1
    db.commit()
    return copied


def clear_rotation(
    db: Session,
    assignment_date: date,
    call_group_id: int | None,
    *,
    admin: AdminUser | None = None,
) -> None:
    existing = (
        rotation_query_for_assignment(db, assignment_date, call_group_id)
        .options(joinedload(CallRotation.call_group))
        .first()
    )
    if not existing:
        return
    from_surgeon_id = existing.surgeon_id
    rotation_id = existing.id
    group_name = existing.call_group.name if existing.call_group else _group_name(db, call_group_id)
    log_call_schedule_change(
        db,
        action="clear",
        event_date=assignment_date,
        source="portal",
        call_group_id=call_group_id,
        call_group_name=group_name,
        rotation_id=rotation_id,
        from_surgeon_id=from_surgeon_id,
        to_surgeon_id=None,
        actor_admin_id=admin.id if admin else None,
        actor_label=actor_label_for_admin(admin),
    )
    db.delete(existing)
    db.commit()
