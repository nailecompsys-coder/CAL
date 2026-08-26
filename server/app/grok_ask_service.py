"""Ask Grok-BOT: fill slots, then run the live query for that screen.

Not an LLM. Answers come from CAL (and Aprima cache in this DB). PHI stays here.
New miss: add a QUESTION_CATALOG line and a UI-label/topic rule in grok_ask_intent.
Add an answer function only when the screen itself is new.
Secrets, OTP codes, magic links, and device tokens are never in the answer.
"""
from __future__ import annotations

from datetime import date

from sqlalchemy.orm import Session

from . import grok_ask_answers as answers
from .grok_ask_intent import (
    LOCATION_CLINIC_TOPICS,
    LOCATION_VOLUME_TOPICS,
    AskIntent,
    looks_like_live_ask,
    parse_intent,
    parse_topic,
    parse_window,
)
from .practice_time import practice_today

# Tests import parse_topic / parse_window from this module.
__all__ = ["ask_grok", "parse_topic", "parse_window", "parse_intent"]

_EMPTY = (
    "Ask me anything on the Dashboard — Today's Coverage, Surgical Cases Today, "
    "Clinic Visits Today, No Call Today, Available Today, Pending Approvals, "
    "or Meetings This Week."
)

# These screens always answer from the board, even if a name is in the sentence.
_BOARD = {
    "roster": lambda db, intent, uid: answers._answer_roster(db),
    "notices": lambda db, intent, uid: answers._answer_notices(db, uid),
    "groups": lambda db, intent, uid: answers._answer_groups(db),
    "who_off": lambda db, intent, uid: answers._answer_who_off(db, intent.window),
    "who_call": lambda db, intent, uid: answers._answer_who_call(db, intent.window),
    "no_call": lambda db, intent, uid: answers._answer_no_call(db, intent.window),
    "who_clinic": lambda db, intent, uid: answers._answer_who_clinic(db, intent.window),
    "clinic_visits": lambda db, intent, uid: answers._answer_clinic_visits(db, intent.window),
    "available": lambda db, intent, uid: answers._answer_available(db, intent.window),
    "clinics_or": lambda db, intent, uid: answers._answer_clinics_or(db, intent.window),
    "pending_off": lambda db, intent, uid: answers._answer_pending_off(
        db, intent.window, today=intent.today
    ),
}

# Used only when the question did not name a surgeon.
_BOARD_IF_NO_SURGEON = {
    "cases": answers._answer_cases_board,
    "time_off": answers._answer_who_off,
    "clinic": answers._answer_who_clinic,
    "call": answers._answer_who_call,
    "blocks": answers._answer_blocks_board,
}

_SURGEON = {
    "time_off": answers._answer_time_off,
    "clinic": answers._answer_clinic,
    "cases": answers._answer_cases,
    "call": answers._answer_call,
    "meetings": answers._answer_meetings,
    "blocks": answers._answer_blocks,
    "availability": answers._answer_availability,
}


def ask_grok(
    db: Session,
    question: str,
    *,
    today: date | None = None,
    admin_user_id: int | None = None,
) -> dict:
    today = today or practice_today()
    raw = " ".join((question or "").split())
    if not raw:
        return {"ok": False, "answer": _EMPTY}

    intent = parse_intent(db, raw, today)
    if isinstance(intent, dict):
        return intent
    return _dispatch(db, intent, admin_user_id)


def _dispatch(db: Session, intent: AskIntent, admin_user_id: int | None) -> dict:
    if intent.topic == "when":
        return answers._answer_when(intent.question, intent.today)
    if intent.topic == "identity":
        return answers._answer_identity()

    # Named office + clinic/patients beats the board-wide clinic roster.
    if intent.location and intent.topic in LOCATION_CLINIC_TOPICS:
        return answers._answer_location_volume(
            db, intent.location, intent.window, "clinic"
        )

    board = _BOARD.get(intent.topic)
    if board:
        return board(db, intent, admin_user_id)

    if intent.topic == "meetings":
        if intent.surgeon:
            facts = answers.collect_surgeon_facts(
                db, intent.surgeon, intent.window["start"], intent.window["end"]
            )
            return answers._answer_meetings(intent.surgeon, intent.window, facts)
        return answers._answer_meetings_board(db, intent.window)

    if not intent.surgeon and intent.topic in _BOARD_IF_NO_SURGEON:
        return _BOARD_IF_NO_SURGEON[intent.topic](db, intent.window)

    if intent.topic == "board":
        return answers._answer_board(db, intent.window)

    if intent.topic == "location":
        if intent.location:
            return answers._answer_location_details(intent.location)
        return answers._answer_locations_board(db)

    if intent.topic == "contact" and intent.surgeon:
        return answers._answer_contact(intent.surgeon)

    if intent.patient and intent.topic in {"patient", "unknown", "briefing"}:
        return intent.patient

    if intent.surgeon:
        if intent.topic == "contact":
            return answers._answer_contact(intent.surgeon)
        facts = answers.collect_surgeon_facts(
            db, intent.surgeon, intent.window["start"], intent.window["end"]
        )
        fn = _SURGEON.get(intent.topic, answers._answer_briefing)
        return fn(intent.surgeon, intent.window, facts)

    if intent.location and intent.topic in LOCATION_VOLUME_TOPICS:
        return answers._answer_location_volume(
            db, intent.location, intent.window, intent.topic
        )

    if intent.topic in {"briefing", "unknown"} and looks_like_live_ask(intent.question):
        return answers._answer_board(db, intent.window)

    return answers._answer_freeform(intent.question, intent.today)
