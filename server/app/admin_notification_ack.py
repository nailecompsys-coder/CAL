"""Informational admin cards (Grok-BOT / Cal-BOT notes) dismiss on click."""
from __future__ import annotations

import json

from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from .admin_notification_href import admin_notification_href
from .models import AdminNotification

_BOT_KINDS = frozenset({"clippy", "grok", "grok_bot", "cal_bot"})
_FIXABLE_KINDS = frozenset({
    "schedule_flag",
    "ingest_correction",
    "call_coverage_conflict",
    "rules_engine_error",
})


def notification_is_bot_chatter(row: AdminNotification | None) -> bool:
    """True for Cal-BOT diary notes: greetings, 'found it', and 'no longer flagged'."""
    if row is None:
        return False
    kind = (row.kind or "").strip().lower()
    title = (row.title or "").strip().lower()
    body = (row.body or "").strip().lower()
    if kind in _BOT_KINDS:
        return True
    if "cal-bot" in title or "grok-bot" in title or title == "grok":
        return True
    if "no longer flagged" in body:
        return True
    return False


def notification_is_informational(row: AdminNotification | None) -> bool:
    """True for bot notes and 'already happened' messages — click should remove them."""
    if row is None:
        return False
    if notification_is_bot_chatter(row):
        return True
    kind = (row.kind or "").strip().lower()
    title = (row.title or "").strip().lower()
    body = (row.body or "").strip().lower()
    if kind == "day_off_request" and ("cancel" in title or "cancel" in body):
        return True
    if kind in _FIXABLE_KINDS:
        return False
    if kind in {"day_off_request", "day_off_duplicate"}:
        return False
    return True


def reconcile_bot_chatter_notifications(
    db: Session,
    admin_user_id: int | None = None,
) -> int:
    """Drop Cal-BOT feed notes. A fixed clash should vanish, not get a second 'cleared' card."""
    q = db.query(AdminNotification)
    if admin_user_id is not None:
        q = q.filter(AdminNotification.admin_user_id == admin_user_id)
    q = q.filter(
        or_(
            AdminNotification.kind.in_(tuple(_BOT_KINDS)),
            func.lower(AdminNotification.title).in_(("cal-bot", "grok", "grok-bot", "grok bot")),
            func.lower(AdminNotification.body).like("%no longer flagged%"),
        )
    )
    removed = 0
    for row in q.all():
        db.delete(row)
        removed += 1
    if removed:
        db.commit()
    return removed


def ack_informational_notification(
    db: Session,
    admin_user_id: int,
    notification_id: int,
) -> str:
    """Delete an informational card and return where to send the admin next."""
    row = db.get(AdminNotification, notification_id)
    if row is None or row.admin_user_id != admin_user_id:
        return "/admin/dashboard"
    try:
        payload = json.loads(row.payload or "{}") if row.payload else {}
    except (TypeError, ValueError):
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    href = admin_notification_href(row.kind, payload) or "/admin/dashboard"
    if notification_is_informational(row):
        db.delete(row)
        db.commit()
    return href
