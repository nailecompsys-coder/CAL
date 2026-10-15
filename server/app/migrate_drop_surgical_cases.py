"""Copy old surgery rows onto the card that already owns that day, then drop the list.

A row with no morning or afternoon card is not a schedule. It goes away with the list.
"""

from sqlalchemy import text

from .database import engine

_COPY_SQL = """
INSERT INTO schedule_card_activities (
    schedule_card_id,
    surgeon_id,
    location_id,
    activity_date,
    session,
    activity_type,
    start_time,
    end_time,
    patient_name,
    procedure,
    room_text,
    source_system,
    source_record_key,
    identity_key,
    or_block_instance_id,
    is_active
)
SELECT
    card.id,
    card.surgeon_id,
    sc.location_id,
    card.date,
    card.session,
    'surgical',
    sc.start_time,
    sc.end_time,
    COALESCE(NULLIF(btrim(sc.patient_name), ''), 'Patient'),
    COALESCE(sc.procedure, ''),
    NULLIF(btrim(COALESCE(sc.room_text, '')), ''),
    'surgical_case',
    sc.id::text,
    lower(regexp_replace(COALESCE(sc.patient_name, ''), '[^a-zA-Z0-9]+', '', 'g'))
        || '|'
        || COALESCE(to_char(sc.start_time, 'HH24:MI:SS'), '')
        || '|surgical',
    CASE
        WHEN EXISTS (
            SELECT 1 FROM or_block_instances block WHERE block.id = sc.or_block_instance_id
        ) THEN sc.or_block_instance_id
        ELSE NULL
    END,
    COALESCE(sc.status, 'scheduled') IS DISTINCT FROM 'cancelled'
FROM surgical_cases sc
JOIN LATERAL (
    SELECT picked.*
    FROM schedule_cards picked
    WHERE (
            picked.id = sc.schedule_card_id
            AND picked.surgeon_id = sc.surgeon_id
            AND picked.date = sc.date
        )
        OR (
            NOT EXISTS (
                SELECT 1
                FROM schedule_cards pinned
                WHERE pinned.id = sc.schedule_card_id
                  AND pinned.surgeon_id = sc.surgeon_id
                  AND pinned.date = sc.date
            )
            AND picked.surgeon_id = sc.surgeon_id
            AND picked.date = sc.date
            AND picked.session = CASE
                WHEN sc.start_time IS NOT NULL AND sc.start_time >= TIME '12:00' THEN 'pm'
                ELSE 'am'
            END
        )
    ORDER BY CASE WHEN picked.id = sc.schedule_card_id THEN 0 ELSE 1 END, picked.id
    LIMIT 1
) card ON TRUE
ON CONFLICT (source_system, source_record_key) DO NOTHING
"""


def _drop_pointers(conn) -> None:
    if conn.execute(text("SELECT to_regclass('public.schedule_card_activities')")).scalar():
        conn.execute(text(
            "ALTER TABLE schedule_card_activities DROP COLUMN IF EXISTS surgical_case_id"
        ))
    if conn.execute(text("SELECT to_regclass('public.fax_restore_lines')")).scalar():
        conn.execute(text(
            "ALTER TABLE fax_restore_lines DROP COLUMN IF EXISTS surgical_case_id"
        ))


def run_migration() -> None:
    if engine.dialect.name == "sqlite":
        return
    with engine.begin() as conn:
        if conn.execute(text("SELECT to_regclass('public.surgical_cases')")).scalar():
            has_card = conn.execute(text("SELECT to_regclass('public.schedule_cards')")).scalar()
            has_lines = conn.execute(text("SELECT to_regclass('public.schedule_card_activities')")).scalar()
            if has_card and has_lines:
                conn.execute(text(_COPY_SQL))
            for trigger in (
                "surgical_cases_keep_on_unapplied_fax_days",
                "surgical_cases_cancel_needs_two_faxes",
                "surgical_cases_fax_cannot_touch_past",
                "surgical_cases_past_days_cannot_be_deleted",
            ):
                conn.execute(text(f"DROP TRIGGER IF EXISTS {trigger} ON surgical_cases"))
            _drop_pointers(conn)
            conn.execute(text("DROP TABLE surgical_cases CASCADE"))
            return
        _drop_pointers(conn)
