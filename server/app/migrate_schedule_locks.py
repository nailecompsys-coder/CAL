"""Three locks: one person per meeting, one Block OR room, and a card that matches its week."""

import logging

from sqlalchemy import text

from .database import engine

log = logging.getLogger(__name__)


def _constraint_exists(conn, name: str) -> bool:
    return bool(conn.execute(
        text("SELECT 1 FROM pg_constraint WHERE conname = :name"),
        {"name": name},
    ).first())


def apply(conn) -> None:
    _lock_meeting_attendees(conn)
    _lock_or_rooms(conn)
    _lock_card_week_surgeon(conn)


def _lock_meeting_attendees(conn) -> None:
    removed = conn.execute(text("""
        DELETE FROM meeting_attendees AS extra
        USING meeting_attendees AS kept
        WHERE extra.meeting_id = kept.meeting_id
          AND extra.surgeon_id = kept.surgeon_id
          AND extra.id > kept.id
    """)).rowcount
    if not _constraint_exists(conn, "uq_meeting_attendees_meeting_surgeon"):
        conn.execute(text("""
            ALTER TABLE meeting_attendees
                ADD CONSTRAINT uq_meeting_attendees_meeting_surgeon
                UNIQUE (meeting_id, surgeon_id)
        """))
    log.info("meeting attendee duplicates removed=%s", removed or 0)


def _lock_or_rooms(conn) -> None:
    ranked = """
        SELECT id,
               MIN(id) OVER (
                   PARTITION BY location_id, date, COALESCE(session, ''), COALESCE(room_text, '')
               ) AS keep_id
        FROM or_block_instances
    """
    assignments = conn.execute(text(f"""
        UPDATE or_block_assignments AS child
        SET block_instance_id = ranked.keep_id
        FROM ({ranked}) AS ranked
        WHERE child.block_instance_id = ranked.id
          AND ranked.id <> ranked.keep_id
    """)).rowcount
    audits = conn.execute(text(f"""
        UPDATE or_block_audit_events AS child
        SET block_instance_id = ranked.keep_id
        FROM ({ranked}) AS ranked
        WHERE child.block_instance_id = ranked.id
          AND ranked.id <> ranked.keep_id
    """)).rowcount
    has_old_cases = conn.execute(text("""
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = 'surgical_cases'
          AND column_name = 'or_block_instance_id'
    """)).first()
    if has_old_cases:
        conn.execute(text(f"""
            UPDATE surgical_cases AS child
            SET or_block_instance_id = ranked.keep_id
            FROM ({ranked}) AS ranked
            WHERE child.or_block_instance_id = ranked.id
              AND ranked.id <> ranked.keep_id
        """))
    has_line_pointer = conn.execute(text("""
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = 'schedule_card_activities'
          AND column_name = 'or_block_instance_id'
    """)).first()
    lines = 0
    if has_line_pointer:
        lines = conn.execute(text(f"""
            UPDATE schedule_card_activities AS child
            SET or_block_instance_id = ranked.keep_id
            FROM ({ranked}) AS ranked
            WHERE child.or_block_instance_id = ranked.id
              AND ranked.id <> ranked.keep_id
        """)).rowcount
    removed = conn.execute(text(f"""
        DELETE FROM or_block_instances AS extra
        USING ({ranked}) AS ranked
        WHERE extra.id = ranked.id
          AND ranked.id <> ranked.keep_id
    """)).rowcount
    conn.execute(text("""
        CREATE UNIQUE INDEX IF NOT EXISTS uq_or_block_instances_location_date_session_room
        ON or_block_instances (
            location_id,
            date,
            (COALESCE(session, '')),
            (COALESCE(room_text, ''))
        )
    """))
    log.info(
        "block or room duplicates removed=%s assignments=%s audits=%s lines=%s",
        removed or 0,
        assignments or 0,
        audits or 0,
        lines or 0,
    )


def _lock_card_week_surgeon(conn) -> None:
    mismatches = conn.execute(text("""
        SELECT count(*)
        FROM schedule_cards AS card
        JOIN schedule_card_weeks AS week ON week.id = card.week_id
        WHERE card.surgeon_id IS DISTINCT FROM week.surgeon_id
    """)).scalar() or 0
    has_day_off_links = conn.execute(text("""
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = 'day_off_schedule_cards'
          AND column_name = 'schedule_card_id'
    """)).first()
    dropped_links = 0
    if has_day_off_links:
        dropped_links = conn.execute(text("""
            DELETE FROM day_off_schedule_cards AS link
            USING schedule_cards AS card
            JOIN schedule_card_weeks AS week ON week.id = card.week_id
            WHERE link.schedule_card_id = card.id
              AND card.surgeon_id IS DISTINCT FROM week.surgeon_id
        """)).rowcount
    conn.execute(text("""
        UPDATE schedule_cards AS card
        SET surgeon_id = week.surgeon_id
        FROM schedule_card_weeks AS week
        WHERE card.week_id = week.id
          AND card.surgeon_id IS DISTINCT FROM week.surgeon_id
    """))
    if not _constraint_exists(conn, "uq_schedule_card_weeks_id_surgeon"):
        conn.execute(text("""
            ALTER TABLE schedule_card_weeks
                ADD CONSTRAINT uq_schedule_card_weeks_id_surgeon
                UNIQUE (id, surgeon_id)
        """))
    if not _constraint_exists(conn, "fk_schedule_cards_week_surgeon"):
        conn.execute(text("""
            ALTER TABLE schedule_cards
                ADD CONSTRAINT fk_schedule_cards_week_surgeon
                FOREIGN KEY (week_id, surgeon_id)
                REFERENCES schedule_card_weeks (id, surgeon_id)
                ON UPDATE CASCADE
                ON DELETE CASCADE
        """))
    log.info(
        "card week surgeon mismatches=%s day_off_links_dropped=%s",
        mismatches,
        dropped_links or 0,
    )


def run_migration() -> None:
    if engine.dialect.name == "sqlite":
        return
    with engine.begin() as conn:
        apply(conn)
