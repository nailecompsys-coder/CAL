"""Per-surgeon native push alert sound (filename in the iOS app bundle)."""

from sqlalchemy import text

from .database import engine


def run_migration() -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                ALTER TABLE surgeons
                ADD COLUMN IF NOT EXISTS push_sound VARCHAR(64)
                """
            )
        )
        # CJ only for now — more docs get their own bundle sounds later.
        conn.execute(
            text(
                """
                UPDATE surgeons
                SET push_sound = 'bagpipes.wav'
                WHERE is_active IS TRUE
                  AND lower(first_name) LIKE 'christopher%'
                  AND lower(last_name) = 'johnson'
                  AND (push_sound IS NULL OR push_sound = '')
                """
            )
        )
