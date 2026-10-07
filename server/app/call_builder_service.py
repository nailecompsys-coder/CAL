"""Call Builder: access, SQL-owned history, shared draft helpers. Does not touch live call_rotations."""

from __future__ import annotations

from datetime import date
from functools import lru_cache
from pathlib import Path

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from .models import AdminUser, CallDraftAssignment, CallGroup, Holiday, Surgeon


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
