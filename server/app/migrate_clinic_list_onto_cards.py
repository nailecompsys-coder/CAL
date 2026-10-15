"""Copy an old clinic row onto the empty morning and afternoon cards.

A whole-day row fills both cards. A card that already has a place is left alone.
"""

from sqlalchemy import text

from .database import engine

_COPY_SQL = """
UPDATE schedule_cards AS card
SET
    baseline_state = CASE
        WHEN lower(coalesce(cs.assignment_type, 'assigned')) = 'off' THEN 'off'
        ELSE 'assigned'
    END,
    effective_state = CASE
        WHEN lower(coalesce(cs.assignment_type, 'assigned')) = 'off' THEN 'off'
        ELSE 'assigned'
    END,
    baseline_location_id = CASE
        WHEN lower(coalesce(cs.assignment_type, 'assigned')) = 'off' THEN NULL
        ELSE cs.location_id
    END,
    effective_location_id = CASE
        WHEN lower(coalesce(cs.assignment_type, 'assigned')) = 'off' THEN NULL
        ELSE cs.location_id
    END
FROM clinic_schedules AS cs
WHERE card.surgeon_id = cs.surgeon_id
  AND card.date = cs.date
  AND card.effective_state = 'na'
  AND (
        lower(coalesce(cs.session, 'full')) = card.session
        OR (
            lower(coalesce(cs.session, 'full')) = 'full'
            AND NOT EXISTS (
                SELECT 1
                FROM clinic_schedules AS specific
                WHERE specific.surgeon_id = card.surgeon_id
                  AND specific.date = card.date
                  AND lower(coalesce(specific.session, 'full')) = card.session
                  AND (
                        lower(coalesce(specific.assignment_type, 'assigned')) = 'off'
                        OR specific.location_id IS NOT NULL
                  )
            )
        )
  )
  AND (
        lower(coalesce(cs.assignment_type, 'assigned')) = 'off'
        OR cs.location_id IS NOT NULL
  )
"""


def run_migration() -> None:
    if engine.dialect.name == "sqlite":
        return
    with engine.begin() as conn:
        if not conn.execute(text("SELECT to_regclass('public.clinic_schedules')")).scalar():
            return
        if not conn.execute(text("SELECT to_regclass('public.schedule_cards')")).scalar():
            return
        conn.execute(text(_COPY_SQL))
