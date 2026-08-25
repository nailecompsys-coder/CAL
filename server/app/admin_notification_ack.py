"""Informational admin cards (Grok-BOT / Cal-BOT notes) dismiss on click."""
from __future__ import annotations

import json

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


def notification_is_informational(row: AdminNotification | None) -> bool:
    """True for bot notes and 'already happened' messages — click should remove them."""
    if row is None:
        return False
    kind = (row.kind or "").strip().lower()
    title = (row.title or "").strip().lower()
    body = (row.body or "").strip().lower()
    if kind in _BOT_KINDS:
        return True
    if "cal-bot" in title or "grok-bot" in title or title == "grok":
        return True
    if kind == "day_off_request" and ("cancel" in title or "cancel" in body):
        return True
    if kind in _FIXABLE_KINDS:
        return False
    if kind in {"day_off_request", "day_off_duplicate"}:
        return False
    return True


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
