"""Time-off groups: yellow/red counts per group.

Chris (surgeon in charge), Nov 20: counted by group, not the whole practice.
Two doctors in a group off at once is yellow; a third is red. Nothing is blocked.

Additive only. Groups that had the old "Limit approved off per day" switch move
to 2/3 once. A Whole practice group exists but is off unless Shannon turns it on.
"""

from sqlalchemy import text

from .database import engine

WHOLE_PRACTICE_NAME = "Whole practice"
WHOLE_PRACTICE_ABBREVIATION = "ALL"
# Chris (surgeon in charge), Nov 20: two doctors off at once is yellow; a third is red.
GROUP_YELLOW = 2
GROUP_RED = 3
WHOLE_PRACTICE_YELLOW = GROUP_YELLOW
WHOLE_PRACTICE_RED = GROUP_RED


def seed_time_off_groups(conn) -> None:
    """Carry old limits forward and add Whole practice. Safe to run repeatedly."""
    # One time: groups still on the old switch move to 2/3. The switch is turned
    # off so a number Shannon later saves on the Settings page stays put.
    conn.execute(
        text(
            """
            UPDATE clinic_groups
            SET yellow_at_off = :yellow, red_at_off = :red, enforce_day_off_limit = FALSE
            WHERE group_type = 'people'
              AND applies_to_all = FALSE
              AND enforce_day_off_limit = TRUE
            """
        ),
        {"yellow": GROUP_YELLOW, "red": GROUP_RED},
    )
    # One time: the first release's active Whole practice (3/4) is turned off.
    conn.execute(
        text(
            """
            UPDATE clinic_groups
            SET is_active = FALSE, yellow_at_off = :yellow, red_at_off = :red
            WHERE applies_to_all = TRUE AND yellow_at_off = 3 AND red_at_off = 4
            """
        ),
        {"yellow": WHOLE_PRACTICE_YELLOW, "red": WHOLE_PRACTICE_RED},
    )
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
                    :name, :abbr, 'people', FALSE, 1, :yellow, :red, TRUE, FALSE
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


def mark_exempt_surgeons(conn) -> None:
    """One time: Chris Johnson is exempt (Chris, Nov 20). Later changes are made in Settings."""
    already = conn.execute(text(
        "SELECT count(*) FROM surgeons WHERE time_off_exempt = TRUE"
    )).scalar()
    if already:
        return
    conn.execute(text(
        """
        UPDATE surgeons SET time_off_exempt = TRUE
        WHERE is_active = TRUE
          AND lower(first_name) LIKE 'christopher%'
          AND lower(trim(last_name)) = 'johnson'
        """
    ))


def run_migration() -> None:
    with engine.begin() as conn:
        if engine.dialect.name != "sqlite":
            conn.execute(text(
                "ALTER TABLE surgeons ADD COLUMN IF NOT EXISTS time_off_exempt BOOLEAN NOT NULL DEFAULT FALSE"
            ))
            conn.execute(text("ALTER TABLE clinic_groups ADD COLUMN IF NOT EXISTS yellow_at_off INTEGER"))
            conn.execute(text("ALTER TABLE clinic_groups ADD COLUMN IF NOT EXISTS red_at_off INTEGER"))
            conn.execute(text(
                "ALTER TABLE clinic_groups ADD COLUMN IF NOT EXISTS applies_to_all BOOLEAN NOT NULL DEFAULT FALSE"
            ))
        seed_time_off_groups(conn)
        mark_exempt_surgeons(conn)
