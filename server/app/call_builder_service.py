"""Call Builder: access, SQL-owned history, shared draft helpers. Does not touch live call_rotations."""

from __future__ import annotations

import calendar as calendar_lib
from datetime import date, timedelta
from functools import lru_cache
from pathlib import Path

from fastapi import HTTPException
from sqlalchemy import func, text
from sqlalchemy.orm import Session

from .admin_call_schedule_action_service import assign_rotation
from .admin_call_schedule_page_service import month_schedule_days
from .models import (
    AdminUser,
    CallDraftAssignment,
    CallGroup,
    CallRotation,
    DayOff,
    Holiday,
    Surgeon,
)
from .practice_time import practice_today


@lru_cache(maxsize=2)
def _history_statement(dialect: str):
    sql = Path(__file__).with_name("sql").joinpath("call_builder_history.sql").read_text()
    if dialect == "postgresql":
        tokens = {
            "FROM_DATE": "CAST(:from_date AS DATE)",
            "TO_DATE": "CAST(:to_date AS DATE)",
            "DRAFT_FROM": "CAST(:draft_from AS DATE)",
            "DRAFT_TO": "CAST(:draft_to AS DATE)",
            "WEEKDAY_EXPR": "EXTRACT(DOW FROM e.call_date)",
            "WEEKDAY_DRAFT": "EXTRACT(DOW FROM d.call_date)",
            "HOLIDAY_LIST": "string_agg(h.name || '/' || CAST(e.call_group_id AS TEXT), ',' ORDER BY h.date)",
        }
    elif dialect == "sqlite":
        tokens = {
            "FROM_DATE": ":from_date",
            "TO_DATE": ":to_date",
            "DRAFT_FROM": ":draft_from",
            "DRAFT_TO": ":draft_to",
            "WEEKDAY_EXPR": "CAST(strftime('%w', e.call_date) AS INTEGER)",
            "WEEKDAY_DRAFT": "CAST(strftime('%w', d.call_date) AS INTEGER)",
            "HOLIDAY_LIST": "group_concat(h.name || '/' || e.call_group_id)",
        }
    else:
        raise ValueError(f"Unsupported database: {dialect}")
    for token, expression in tokens.items():
        sql = sql.replace(token, expression)
    return text(sql)


def admin_can_call_builder(admin: AdminUser | None) -> bool:
    return bool(admin and getattr(admin, "can_call_builder", False))


def surgeon_can_call_builder(surgeon: Surgeon | None) -> bool:
    return bool(surgeon and getattr(surgeon, "can_call_builder", False))


def require_admin_call_builder(admin: AdminUser) -> None:
    if not admin_can_call_builder(admin):
        raise HTTPException(403, "Call Builder is not enabled for this account")


def require_surgeon_call_builder(surgeon: Surgeon) -> None:
    if not surgeon_can_call_builder(surgeon):
        raise HTTPException(403, "Call Builder is not enabled for this account")


def call_history(
    db: Session,
    *,
    from_date: date,
    to_date: date,
    draft_from: date | None = None,
    draft_to: date | None = None,
) -> list[dict]:
    """Serialize SQL history rows. Python only places fields; no load math."""
    draft_from = draft_from or from_date
    draft_to = draft_to or from_date
    rows = db.execute(
        _history_statement(db.bind.dialect.name),
        {
            "from_date": from_date.isoformat(),
            "to_date": to_date.isoformat(),
            "draft_from": draft_from.isoformat(),
            "draft_to": draft_to.isoformat(),
        },
    ).mappings()
    return [{
        "surgeonId": row["surgeon_id"],
        "initials": row["initials"],
        "lastName": row["last_name"],
        "firstName": row["first_name"],
        "staffType": row["staff_type"],
        "callCount": int(row["call_count"] or 0),
        "weekendCount": int(row["weekend_count"] or 0),
        "monthCallCount": int(row["month_call_count"] or 0),
        "draftCount": int(row["draft_count"] or 0),
        "draftWeekendCount": int(row["draft_weekend_count"] or 0),
        "holidays": row["holidays"] or "",
    } for row in rows]


def holidays_between(db: Session, start: date, end: date) -> list[Holiday]:
    return (
        db.query(Holiday)
        .filter(Holiday.date >= start, Holiday.date <= end)
        .order_by(Holiday.date)
        .all()
    )


def draft_assignments(db: Session, start: date, end: date) -> list[CallDraftAssignment]:
    return (
        db.query(CallDraftAssignment)
        .filter(CallDraftAssignment.date >= start, CallDraftAssignment.date <= end)
        .order_by(CallDraftAssignment.date, CallDraftAssignment.call_group_id)
        .all()
    )


def upsert_draft(
    db: Session,
    *,
    day: date,
    call_group_id: int,
    surgeon_id: int | None,
    admin: AdminUser | None = None,
    surgeon: Surgeon | None = None,
) -> CallDraftAssignment:
    """Place or clear one draft cell. Does not write call_rotations."""
    if admin is None and surgeon is None:
        raise HTTPException(400, "Draft update needs an actor")
    if admin is not None:
        require_admin_call_builder(admin)
    if surgeon is not None:
        require_surgeon_call_builder(surgeon)
    if not db.get(CallGroup, call_group_id):
        raise HTTPException(404, "Call group not found")
    if surgeon_id is not None and not db.get(Surgeon, surgeon_id):
        raise HTTPException(404, "Surgeon not found")

    row = (
        db.query(CallDraftAssignment)
        .filter(
            CallDraftAssignment.date == day,
            CallDraftAssignment.call_group_id == call_group_id,
        )
        .first()
    )
    if row is None:
        row = CallDraftAssignment(date=day, call_group_id=call_group_id)
        db.add(row)
    row.surgeon_id = surgeon_id
    row.updated_by_admin_id = admin.id if admin else None
    row.updated_by_surgeon_id = surgeon.id if surgeon else None
    db.commit()
    db.refresh(row)
    return row


def clear_draft(
    db: Session,
    *,
    day: date,
    call_group_id: int,
    admin: AdminUser | None = None,
    surgeon: Surgeon | None = None,
) -> None:
    if admin is not None:
        require_admin_call_builder(admin)
    if surgeon is not None:
        require_surgeon_call_builder(surgeon)
    row = (
        db.query(CallDraftAssignment)
        .filter(
            CallDraftAssignment.date == day,
            CallDraftAssignment.call_group_id == call_group_id,
        )
        .first()
    )
    if row:
        db.delete(row)
        db.commit()


def clear_draft_month(
    db: Session,
    *,
    start: date,
    end: date,
    admin: AdminUser | None = None,
    surgeon: Surgeon | None = None,
) -> int:
    if admin is not None:
        require_admin_call_builder(admin)
    if surgeon is not None:
        require_surgeon_call_builder(surgeon)
    rows = draft_assignments(db, start, end)
    n = len(rows)
    for row in rows:
        db.delete(row)
    db.commit()
    return n


def short_group_label(group: CallGroup) -> str:
    name = (group.name or "").lower()
    if "altamonte" in name or name.startswith("alt"):
        return "ALT"
    return "WG"


def _is_no_call(reason: str | None) -> bool:
    return " ".join((reason or "").strip().lower().split()) == "no call"


def leave_flag_map(db: Session, start: date, end: date) -> dict[str, str]:
    """Keys are 'YYYY-MM-DD|surgeon_id' → 'Off' or 'No Call' (approved only)."""
    rows = (
        db.query(DayOff)
        .filter(
            DayOff.status == "approved",
            DayOff.start_date <= end,
            DayOff.end_date >= start,
        )
        .all()
    )
    out: dict[str, str] = {}
    for row in rows:
        kind = "No Call" if _is_no_call(row.reason) else "Off"
        current = max(row.start_date, start)
        last = min(row.end_date, end)
        while current <= last:
            key = f"{current.isoformat()}|{row.surgeon_id}"
            # No Call wins over Off if both somehow present
            if key not in out or kind == "No Call":
                out[key] = kind
            current += timedelta(days=1)
    return out


def published_map(db: Session, start: date, end: date) -> dict[str, int | None]:
    """Keys 'YYYY-MM-DD|group_id' → surgeon_id (None = NO call row)."""
    rows = (
        db.query(CallRotation)
        .filter(CallRotation.date >= start, CallRotation.date <= end)
        .all()
    )
    return {
        f"{row.date.isoformat()}|{row.call_group_id}": row.surgeon_id
        for row in rows
        if row.call_group_id is not None
    }


def draft_map(db: Session, start: date, end: date) -> dict[str, int | None]:
    return {
        f"{row.date.isoformat()}|{row.call_group_id}": row.surgeon_id
        for row in draft_assignments(db, start, end)
    }


def publish_changes(db: Session, start: date, end: date) -> list[dict]:
    """Diff draft vs live Call Schedule for the month. Does not write."""
    groups = {g.id: g for g in db.query(CallGroup).order_by(CallGroup.sort_order, CallGroup.id).all()}
    surgeons = {s.id: s for s in db.query(Surgeon).all()}
    live = published_map(db, start, end)
    draft = draft_map(db, start, end)
    leave = leave_flag_map(db, start, end)
    changes = []
    for key, surgeon_id in sorted(draft.items()):
        day_s, group_s = key.split("|", 1)
        group_id = int(group_s)
        live_id = live.get(key, object())  # missing live cell ≠ None (NO call)
        if live_id is surgeon_id:
            continue
        group = groups.get(group_id)
        to_s = surgeons.get(surgeon_id) if surgeon_id else None
        from_s = surgeons.get(live_id) if isinstance(live_id, int) else None
        changes.append({
            "date": day_s,
            "callGroupId": group_id,
            "group": short_group_label(group) if group else str(group_id),
            "groupName": group.name if group else "",
            "fromSurgeonId": live_id if isinstance(live_id, int) else None,
            "fromInitials": from_s.initials if from_s else ("NC" if key in live and live[key] is None else "—"),
            "toSurgeonId": surgeon_id,
            "toInitials": to_s.initials if to_s else "NC",
            "flag": leave.get(f"{day_s}|{surgeon_id}", "") if surgeon_id else "",
        })
    return changes


def publish_draft(
    db: Session,
    *,
    start: date,
    end: date,
    admin: AdminUser,
) -> list[str]:
    """Write draft cells through the same assign path as Call Schedule, then clear them."""
    require_admin_call_builder(admin)
    warnings: list[str] = []
    changes = publish_changes(db, start, end)
    for change in changes:
        day = date.fromisoformat(change["date"])
        group_id = change["callGroupId"]
        to_id = change["toSurgeonId"]
        warnings.extend(assign_rotation(db, day, to_id, group_id, admin=admin) or [])
        clear_draft(db, day=day, call_group_id=group_id, admin=admin)
    return warnings


def page_data(db: Session, month_offset: int) -> dict:
    month = month_schedule_days(month_offset)
    days: list[date] = month["schedule_days"]
    start, end = days[0], days[-1]
    # History: year through end of this month (published call days); draft = this month
    history_from = date(start.year, 1, 1)
    month_end = end + timedelta(days=1)
    history = call_history(
        db,
        from_date=history_from,
        to_date=month_end,
        draft_from=start,
        draft_to=month_end,
    )
    groups = db.query(CallGroup).order_by(CallGroup.sort_order, CallGroup.id).all()
    surgeons = {
        s.id: s
        for s in db.query(Surgeon)
        .filter(Surgeon.is_active.is_(True), func.coalesce(Surgeon.staff_type, "physician") == "physician")
        .all()
    }
    leave = leave_flag_map(db, start, end)
    live = published_map(db, start, end)
    draft = draft_map(db, start, end)
    holidays = {h.date.isoformat(): h.name for h in holidays_between(db, start, end)}
    cells = []
    for day in days:
        for group in groups:
            key = f"{day.isoformat()}|{group.id}"
            draft_id = draft.get(key) if key in draft else None
            has_draft = key in draft
            live_id = live.get(key) if key in live else None
            has_live = key in live
            surgeon_id = draft_id if has_draft else live_id
            source = "draft" if has_draft else ("live" if has_live else "empty")
            flag = leave.get(f"{day.isoformat()}|{surgeon_id}", "") if surgeon_id else ""
            surg = surgeons.get(surgeon_id) if surgeon_id else None
            cells.append({
                "date": day.isoformat(),
                "day": day.day,
                "weekday": day.weekday(),  # Mon=0
                "callGroupId": group.id,
                "group": short_group_label(group),
                "surgeonId": surgeon_id,
                "initials": surg.initials if surg else ("NC" if source != "empty" and surgeon_id is None else ""),
                "source": source,
                "flag": flag,
                "holiday": holidays.get(day.isoformat(), ""),
            })
    cells_by_key = {f"{c['date']}|{c['callGroupId']}": c for c in cells}
    return {
        **month,
        "month_offset": month_offset,
        "groups": [{"id": g.id, "name": g.name, "short": short_group_label(g)} for g in groups],
        "history": history,
        "cells": cells,
        "cells_by_key": cells_by_key,
        "leave": leave,
        "holidays": holidays,
        "draft_count": len(draft),
        "change_count": len(publish_changes(db, start, end)),
        "today": practice_today(),
        "days_in_month": calendar_lib.monthrange(start.year, start.month)[1],
        "year": start.year,
        "month": start.month,
        "month_short": start.strftime("%b"),
    }
