"""Services for admin call schedule pages and actions."""

import calendar as calendar_lib
from datetime import date, timedelta

from sqlalchemy.orm import Session, joinedload

from .conflicts import check_conflicts
from .models import CallCoverage, CallGroup, CallRotation, DayOff, Location, Surgeon
from .push import send_push_to_surgeon


def parse_call_group_id(raw: str | int | None) -> int | None:
    if raw is None:
        return None
    if isinstance(raw, int):
        return raw
    value = (raw or "").strip()
    return int(value) if value else None


def month_schedule_days(month_offset: int) -> dict:
    today = date.today()
    total_months = today.year * 12 + (today.month - 1) + month_offset
    year = total_months // 12
    month = total_months % 12 + 1
    first_day = date(year, month, 1)
    days_in_month = calendar_lib.monthrange(year, month)[1]
    schedule_days = [date(year, month, day) for day in range(1, days_in_month + 1)]
    return {
        "today": today,
        "schedule_days": schedule_days,
        "month_label": first_day.strftime("%B %Y"),
        "pad_start": (first_day.weekday() + 1) % 7,
    }


def day_off_by_date(db: Session, schedule_days: list[date], surgeon_sort_key) -> dict[date, dict[str, list[Surgeon]]]:
    day_off_rows = (
        db.query(DayOff)
        .options(joinedload(DayOff.surgeon))
        .filter(
            DayOff.start_date <= schedule_days[-1],
            DayOff.end_date >= schedule_days[0],
            DayOff.status.in_(["pending", "approved"]),
        )
        .all()
    )
    by_date: dict[date, dict[str, list[Surgeon]]] = {
        day: {"pending": [], "approved": []} for day in schedule_days
    }
    seen_initials: dict[date, dict[str, set[str]]] = {
        day: {"pending": set(), "approved": set()} for day in schedule_days
    }
    for row in day_off_rows:
        if not row.surgeon or not row.surgeon.is_active:
            continue
        status = "approved" if row.status == "approved" else "pending"
        current = max(row.start_date, schedule_days[0])
        end = min(row.end_date, schedule_days[-1])
        while current <= end:
            initials = (row.surgeon.initials or "").strip()
            if initials and initials not in seen_initials[current][status]:
                by_date[current][status].append(row.surgeon)
                seen_initials[current][status].add(initials)
            current += timedelta(days=1)
    for status_groups in by_date.values():
        for surgeons_for_status in status_groups.values():
            surgeons_for_status.sort(key=surgeon_sort_key)
    return by_date


def call_group_rows(db: Session, call_groups: list[CallGroup], schedule_days: list[date]) -> list[tuple[CallGroup, dict]]:
    rotations = (
        db.query(CallRotation)
        .options(
            joinedload(CallRotation.surgeon),
            joinedload(CallRotation.coverages).joinedload(CallCoverage.covering_surgeon),
        )
        .filter(
            CallRotation.date >= schedule_days[0],
            CallRotation.date <= schedule_days[-1],
        )
        .all()
    )

    rotation_by_group_date = {}
    for rotation in rotations:
        if rotation.call_group_id is None:
            continue
        by_date = rotation_by_group_date.setdefault(rotation.call_group_id, {})
        if rotation.date not in by_date:
            by_date[rotation.date] = rotation

    seen_names = set()
    rows = []
    for call_group in call_groups:
        if call_group.name in seen_names:
            continue
        seen_names.add(call_group.name)
        merged_rotations = dict(rotation_by_group_date.get(call_group.id, {}))
        for other in call_groups:
            if other.id != call_group.id and other.name == call_group.name:
                for day, rotation in rotation_by_group_date.get(other.id, {}).items():
                    if day not in merged_rotations:
                        merged_rotations[day] = rotation
        rows.append((call_group, merged_rotations))
    return rows


def page_data(db: Session, month_offset: int, surgeon_sort_key) -> dict:
    month_data = month_schedule_days(month_offset)
    schedule_days = month_data["schedule_days"]
    call_groups = db.query(CallGroup).order_by(CallGroup.sort_order, CallGroup.name, CallGroup.id).all()
    return {
        **month_data,
        "group_rows": call_group_rows(db, call_groups, schedule_days),
        "day_off_by_date": day_off_by_date(db, schedule_days, surgeon_sort_key),
        "call_groups": call_groups,
        "locations": db.query(Location).filter(Location.is_active == True).order_by(Location.name).all(),  # noqa: E712
    }


def rotation_query_for_assignment(db: Session, assignment_date: date, call_group_id: int | None):
    query = db.query(CallRotation).filter(CallRotation.date == assignment_date)
    if call_group_id is not None:
        return query.filter(CallRotation.call_group_id == call_group_id)
    return query.filter(CallRotation.call_group_id.is_(None))


def assign_rotation(
    db: Session,
    assignment_date: date,
    surgeon_id: int | None,
    call_group_id: int | None,
) -> list[str]:
    existing = rotation_query_for_assignment(db, assignment_date, call_group_id).first()
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


def clear_rotation(db: Session, assignment_date: date, call_group_id: int | None) -> None:
    rotation_query_for_assignment(db, assignment_date, call_group_id).delete()
    db.commit()
