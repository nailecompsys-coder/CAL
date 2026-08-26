"""Grok-BOT rule maker: plain-language instructions he follows on the live board.

Built-in handlers are code. Custom rows are standing notes he keeps in the briefing.
Turning a rule off means he stops doing that work.
"""
from __future__ import annotations

import re
import secrets
from dataclasses import dataclass

from sqlalchemy.orm import Session

from .models import GrokBotRule
from .practice_time import practice_today

GROK_NOTICE_DATE_PASSED = "GROK_NOTICE_DATE_PASSED"
GROK_PLACE_WITHOUT_TIME = "GROK_PLACE_WITHOUT_TIME"
GROK_COVER_WHILE_OFF = "GROK_COVER_WHILE_OFF"
GROK_ON_CALL_WHILE_OFF = "GROK_ON_CALL_WHILE_OFF"
GROK_OFF_WITH_WORK = "GROK_OFF_WITH_WORK"
GROK_FIXED_MEANS_GONE = "GROK_FIXED_MEANS_GONE"
GROK_DROP_BOT_CHATTER = "GROK_DROP_BOT_CHATTER"


@dataclass(frozen=True)
class GrokRuleSeed:
    rule_id: str
    title: str
    instruction: str
    sort_order: int


BUILTIN_RULES: tuple[GrokRuleSeed, ...] = (
    GrokRuleSeed(
        GROK_NOTICE_DATE_PASSED,
        "Past notices leave the board",
        "If a notice has a date that has already passed, take it off the board.",
        10,
    ),
    GrokRuleSeed(
        GROK_PLACE_WITHOUT_TIME,
        "No clock still goes on the schedule",
        (
            "If a fax row still has no start time after reading OCR again, put the case "
            "on that day without a time. Do not invent a clock. Do not leave a missing-time "
            "card. They can add the time when they get to the OR."
        ),
        20,
    ),
    GrokRuleSeed(
        GROK_COVER_WHILE_OFF,
        "Covering call while off",
        (
            "If a doctor is covering call and also has time off that day, say so. "
            "Time off does not cover call."
        ),
        30,
    ),
    GrokRuleSeed(
        GROK_ON_CALL_WHILE_OFF,
        "On call with no cover while off",
        (
            "If a doctor is on call, has time off that day, and nobody is covering, say so."
        ),
        40,
    ),
    GrokRuleSeed(
        GROK_OFF_WITH_WORK,
        "Time off with clinic or OR still on",
        (
            "If a doctor has time off but still has clinic or OR work that day, say so."
        ),
        50,
    ),
    GrokRuleSeed(
        GROK_FIXED_MEANS_GONE,
        "Fixed means gone",
        (
            "When a conflict is fixed, drop the card. Do not leave it sitting as read."
        ),
        60,
    ),
    GrokRuleSeed(
        GROK_DROP_BOT_CHATTER,
        "Drop leftover bot chatter",
        (
            "Drop leftover Cal-BOT / Grok chatter cards that are not real schedule work."
        ),
        70,
    ),
)

_MATCHERS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        GROK_NOTICE_DATE_PASSED,
        (
            "date that has passed",
            "date has passed",
            "already passed",
            "past date",
            "notice has a date",
        ),
    ),
    (
        GROK_PLACE_WITHOUT_TIME,
        (
            "without a time",
            "no start time",
            "missing start time",
            "missing time",
            "add it when they get to the or",
            "add the time at the or",
        ),
    ),
    (
        GROK_COVER_WHILE_OFF,
        ("covering call", "cover while off", "covering and also has time off"),
    ),
    (
        GROK_ON_CALL_WHILE_OFF,
        ("on call", "no cover"),
    ),
    (
        GROK_OFF_WITH_WORK,
        ("time off but still has", "off with clinic", "off with or"),
    ),
    (
        GROK_FIXED_MEANS_GONE,
        ("fixed means gone", "drop the card", "not leave it as read"),
    ),
    (
        GROK_DROP_BOT_CHATTER,
        ("bot chatter", "cal-bot", "leftover chatter"),
    ),
)


def match_plain_language(text: str) -> str | None:
    """Map a plain-English rule to a built-in handler, or None if it is custom."""
    blob = " ".join((text or "").lower().split())
    if not blob:
        return None
    hits: list[str] = []
    for rule_id, phrases in _MATCHERS:
        if any(phrase in blob for phrase in phrases):
            hits.append(rule_id)
    if GROK_COVER_WHILE_OFF in hits and GROK_ON_CALL_WHILE_OFF in hits:
        if "cover" in blob and "on call" not in blob:
            hits = [GROK_COVER_WHILE_OFF]
        elif "on call" in blob:
            hits = [GROK_ON_CALL_WHILE_OFF]
    if len(hits) == 1:
        return hits[0]
    return None


def ensure_grok_bot_rules_seeded(db: Session) -> None:
    existing = {row.rule_id: row for row in db.query(GrokBotRule).all()}
    dirty = False
    for seed in BUILTIN_RULES:
        row = existing.get(seed.rule_id)
        if row is None:
            db.add(
                GrokBotRule(
                    rule_id=seed.rule_id,
                    title=seed.title,
                    instruction=seed.instruction,
                    handler=seed.rule_id,
                    enabled=True,
                    is_builtin=True,
                    sort_order=seed.sort_order,
                )
            )
            dirty = True
            continue
        row.is_builtin = True
        row.handler = seed.rule_id
        if not (row.title or "").strip():
            row.title = seed.title
        if not (row.instruction or "").strip():
            row.instruction = seed.instruction
        dirty = True
    if dirty:
        db.commit()


def list_grok_bot_rules(db: Session) -> list[GrokBotRule]:
    ensure_grok_bot_rules_seeded(db)
    return (
        db.query(GrokBotRule)
        .order_by(GrokBotRule.sort_order, GrokBotRule.id)
        .all()
    )


def grok_rule_enabled(db: Session, rule_id: str) -> bool:
    ensure_grok_bot_rules_seeded(db)
    row = db.query(GrokBotRule).filter(GrokBotRule.rule_id == rule_id).first()
    if row is None:
        return True
    return bool(row.enabled)


def standing_instructions(db: Session) -> list[str]:
    """Enabled custom notes plus any builtin text Grok should keep in mind."""
    notes: list[str] = []
    for row in list_grok_bot_rules(db):
        if not row.enabled:
            continue
        if row.is_builtin:
            continue
        text = (row.instruction or "").strip()
        if text:
            notes.append(text)
    return notes


def save_grok_bot_rules(db: Session, form) -> None:
    ensure_grok_bot_rules_seeded(db)
    for row in db.query(GrokBotRule).all():
        enabled_key = f"rule_{row.id}_enabled"
        title_key = f"rule_{row.id}_title"
        instruction_key = f"rule_{row.id}_instruction"
        if enabled_key in form or f"rule_{row.id}_present" in form:
            row.enabled = form.get(enabled_key) == "1"
        title = (form.get(title_key) or "").strip()
        if title:
            row.title = title[:128]
        instruction = (form.get(instruction_key) or "").strip()
        if instruction:
            row.instruction = instruction
    db.commit()


def add_grok_bot_rule(db: Session, instruction: str, title: str = "") -> GrokBotRule:
    """Add a plain-language rule. Matching built-ins get that wording and stay on."""
    ensure_grok_bot_rules_seeded(db)
    text = (instruction or "").strip()
    if not text:
        raise ValueError("Write the rule in plain language.")
    matched = match_plain_language(text)
    if matched:
        row = db.query(GrokBotRule).filter(GrokBotRule.rule_id == matched).one()
        row.instruction = text
        row.enabled = True
        label = (title or "").strip()
        if label:
            row.title = label[:128]
        db.commit()
        return row
    label = (title or "").strip() or _title_from_instruction(text)
    last = (
        db.query(GrokBotRule)
        .order_by(GrokBotRule.sort_order.desc(), GrokBotRule.id.desc())
        .first()
    )
    sort_order = (last.sort_order if last else 100) + 10
    row = GrokBotRule(
        rule_id=f"GROK_CUSTOM_{secrets.token_hex(4)}",
        title=label[:128],
        instruction=text,
        handler="",
        enabled=True,
        is_builtin=False,
        sort_order=sort_order,
    )
    db.add(row)
    db.commit()
    return row


def delete_grok_bot_rule(db: Session, rule_pk: int) -> bool:
    row = db.get(GrokBotRule, rule_pk)
    if row is None or row.is_builtin:
        return False
    db.delete(row)
    db.commit()
    return True


def _title_from_instruction(text: str) -> str:
    first = re.split(r"[.\n]", text.strip(), maxsplit=1)[0].strip()
    if len(first) > 72:
        first = first[:69].rstrip() + "…"
    return first or "Custom Grok-BOT rule"


def notice_date_has_passed(payload_date: str | None, *, today=None) -> bool:
    from .ingest_date_rules import parse_iso_date

    day = parse_iso_date(payload_date)
    if day is None:
        return False
    return day < (today or practice_today())
