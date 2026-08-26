"""Shared scheduling conflict detection. Uses the rules engine; returns legacy list[str] for compatibility."""
import logging
from datetime import date
from typing import Optional

from sqlalchemy.orm import Session

from .rules_engine import evaluate
from .rules_engine.engine import conflicts_to_messages

log = logging.getLogger(__name__)


def check_conflicts(
    surgeon_id: int,
    start_date: date,
    end_date: date,
    db: Session,
    exclude_dayoff_id: Optional[int] = None,
    exclude_surgical_case_id: Optional[int] = None,
    exclude_call_rotation_id: Optional[int] = None,
    exclude_meeting_id: Optional[int] = None,
    exclude_clinic_schedule_id: Optional[int] = None,
    target_entity: Optional[dict] = None,
) -> list[str]:
    """
    Return human-readable conflict strings for a surgeon over [start_date, end_date].
    Uses the scheduling rules engine; only enabled rules run. Pass exclude_* for the
    entity being saved so it is not reported as a conflict.
    """
    exclude_entity: Optional[tuple[str, int]] = None
    if exclude_dayoff_id is not None:
        exclude_entity = ("day_off", exclude_dayoff_id)
    elif exclude_surgical_case_id is not None:
        exclude_entity = ("surgical_case", exclude_surgical_case_id)
    elif exclude_call_rotation_id is not None:
        exclude_entity = ("call_rotation", exclude_call_rotation_id)
    elif exclude_meeting_id is not None:
        exclude_entity = ("meeting", exclude_meeting_id)
    elif exclude_clinic_schedule_id is not None:
        exclude_entity = ("clinic_schedule", exclude_clinic_schedule_id)

    conflicts = evaluate(
        surgeon_id,
        start_date,
        end_date,
        db,
        exclude_entity=exclude_entity,
        target_entity=target_entity,
    )
    _run_grok_behind_valerie(db)
    return [c.message for c in conflicts]


def check_conflicts_structured(
    surgeon_id: int,
    start_date: date,
    end_date: date,
    db: Session,
    exclude_entity: Optional[tuple[str, int]] = None,
    target_entity: Optional[dict] = None,
) -> list:
    """Return structured Conflict objects (rule_id, message, entity type/id, etc.) for UI or API."""
    return evaluate(
        surgeon_id,
        start_date,
        end_date,
        db,
        exclude_entity=exclude_entity,
        target_entity=target_entity,
    )


def _run_grok_behind_valerie(db: Session) -> None:
    """Valerie already checked the save. Grok sweeps the board next."""
    try:
        from .grok_lookahead_service import run_grok_rules
        run_grok_rules(db)
    except Exception:
        log.exception("Grok-BOT rules failed after a schedule save")
