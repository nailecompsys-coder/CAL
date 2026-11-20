"""Time-off groups: yellow/red counts per group and a Whole practice group.

Additive only. Existing groups that had "Limit approved off per day" keep that
number as the count allowed off: one more is yellow, two more is red.
"""

from sqlalchemy import text

from .database import engine

WHOLE_PRACTICE_NAME = "Whole practice"
WHOLE_PRACTICE_ABBREVIATION = "ALL"
# Chris (surgeon in charge): 2 off already -> the 3rd is yellow; 3 off -> the 4th is red.
WHOLE_PRACTICE_YELLOW = 3
WHOLE_PRACTICE_RED = 4


def seed_time_off_groups(conn) -> None:
    """Carry old limits forward and add Whole practice. Safe to run repeatedly."""
    conn.execute(text(
        """
        UPDATE clinic_groups
        SET yellow_at_off = max_approved_off_per_day + 1,
            red_at_off = max_approved_off_per_day + 2
        WHERE group_type = 'people'
          AND enforce_day_off_limit = TRUE
          AND yellow_at_off IS NULL
          AND red_at_off IS NULL
        """
    ))
    has_whole = conn.execute(text(
        "SELECT count(*) FROM clinic_groups WHERE applies_to_all = TRUE"
    )).scalar()
    name_taken = conn.execute(
        text("SELECT count(*) FROM clinic_groups WHERE name = :name"),
        {"name": WHOLE_PRACTICE_NAME},
    ).scalar()
    if not has_whole and not name_taken:
        conn.execute(
            text(
                """
                INSERT INTO clinic_groups (
                    name, abbreviation, group_type, enforce_day_off_limit,
                    max_approved_off_per_day, yellow_at_off, red_at_off,
                    applies_to_all, is_active
                ) VALUES (
                    :name, :abbr, 'people', FALSE, 1, :yellow, :red, TRUE, TRUE
                )
                """
            ),
            {
                "name": WHOLE_PRACTICE_NAME,
                "abbr": WHOLE_PRACTICE_ABBREVIATION,
                "yellow": WHOLE_PRACTICE_YELLOW,
                "red": WHOLE_PRACTICE_RED,
            },
        )


def run_migration() -> None:
    with engine.begin() as conn:
        if engine.dialect.name != "sqlite":
            conn.execute(text("ALTER TABLE clinic_groups ADD COLUMN IF NOT EXISTS yellow_at_off INTEGER"))
            conn.execute(text("ALTER TABLE clinic_groups ADD COLUMN IF NOT EXISTS red_at_off INTEGER"))
            conn.execute(text(
                "ALTER TABLE clinic_groups ADD COLUMN IF NOT EXISTS applies_to_all BOOLEAN NOT NULL DEFAULT FALSE"
            ))
        seed_time_off_groups(conn)
