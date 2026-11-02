"""Copy Aprima meetings and Surgery One rows onto the real tables, then drop the scratch list."""

import logging

from sqlalchemy import text

from .database import engine

log = logging.getLogger(__name__)


def apply(conn) -> None:
    conn.execute(text(
        "ALTER TABLE meetings ADD COLUMN IF NOT EXISTS source_system VARCHAR(32)"
    ))
    conn.execute(text(
        "ALTER TABLE meetings ADD COLUMN IF NOT EXISTS source_record_key VARCHAR(640)"
    ))
    copied_meetings = 0
    copied_lines = 0
    if conn.execute(text("SELECT to_regclass('public.aprima_cached_appointments')")).scalar():
        copied_meetings = conn.execute(text("""
            INSERT INTO meetings (
                title, date, start_time, end_time, location_text, notes,
                source_system, source_record_key
            )
            SELECT
                left(coalesce(
                    nullif(btrim(regexp_replace(
                        coalesce(nullif(btrim(reason_text), ''), nullif(btrim(appointment_type), ''), 'Meeting'),
                        '^[Mm]eeting[[:space:]:\\-]*',
                        ''
                    )), ''),
                    'Meeting'
                ), 255),
                date,
                start_time,
                end_time,
                left(coalesce(nullif(btrim(service_site), ''), nullif(btrim(room_text), '')), 255),
                reason_text,
                'aprima',
                appointment_id
            FROM aprima_cached_appointments AS cached
            WHERE cached.kind = 'meeting'
              AND NOT EXISTS (
                  SELECT 1 FROM meetings AS saved
                  WHERE saved.source_system = 'aprima'
                    AND saved.source_record_key = cached.appointment_id
              )
        """)).rowcount or 0
        conn.execute(text("""
            INSERT INTO meeting_attendees (meeting_id, surgeon_id, status)
            SELECT meeting.id, cached.surgeon_id, 'invited'
            FROM meetings AS meeting
            JOIN aprima_cached_appointments AS cached
              ON cached.appointment_id = meeting.source_record_key
             AND cached.kind = 'meeting'
            WHERE meeting.source_system = 'aprima'
              AND cached.surgeon_id IS NOT NULL
              AND NOT EXISTS (
                  SELECT 1 FROM meeting_attendees AS attendee
                  WHERE attendee.meeting_id = meeting.id
                    AND attendee.surgeon_id = cached.surgeon_id
              )
        """))
        copied_lines = conn.execute(text("""
            INSERT INTO schedule_card_activities (
                schedule_card_id, surgeon_id, location_id, activity_date, session,
                activity_type, start_time, end_time, patient_name, procedure, room_text,
                source_system, source_record_key, aprima_appointment_id, identity_key, is_active
            )
            SELECT
                card.id,
                card.surgeon_id,
                coalesce(cached.location_id, card.effective_location_id),
                card.date,
                card.session,
                CASE WHEN cached.activity_type = 'surgical' THEN 'surgical' ELSE 'clinic' END,
                cached.start_time,
                cached.end_time,
                left(coalesce(nullif(btrim(cached.patient_name), ''), 'Patient'), 255),
                coalesce(cached.appointment_type, ''),
                cached.room_text,
                'aprima',
                cached.appointment_id,
                cached.appointment_id,
                cached.appointment_id,
                TRUE
            FROM aprima_cached_appointments AS cached
            JOIN schedule_cards AS card ON card.id = cached.schedule_card_id
            WHERE cached.kind = 'patient'
              AND cached.activity_type IS DISTINCT FROM 'meeting'
              AND NOT EXISTS (
                  SELECT 1 FROM schedule_card_activities AS line
                  WHERE line.source_system = 'aprima'
                    AND line.source_record_key = cached.appointment_id
              )
        """)).rowcount or 0
        conn.execute(text("""
            DO $$
            DECLARE bad_name text;
            BEGIN
              FOR bad_name IN
                SELECT con.conname
                FROM pg_constraint con
                JOIN pg_class rel ON rel.oid = con.conrelid
                JOIN pg_namespace nsp ON nsp.oid = rel.relnamespace
                JOIN pg_attribute att
                  ON att.attrelid = rel.oid
                 AND att.attnum = ANY (con.conkey)
                WHERE nsp.nspname = 'public'
                  AND rel.relname = 'schedule_card_activities'
                  AND con.contype = 'f'
                  AND att.attname = 'aprima_appointment_id'
              LOOP
                EXECUTE format('ALTER TABLE schedule_card_activities DROP CONSTRAINT %I', bad_name);
              END LOOP;
            END $$
        """))
        conn.execute(text("DROP TABLE aprima_cached_appointments"))
    conn.execute(text("""
        UPDATE schedule_card_activities
        SET aprima_appointment_id = left(source_record_key, 36)
        WHERE source_system = 'aprima'
          AND aprima_appointment_id IS NULL
    """))
    conn.execute(text("""
        CREATE UNIQUE INDEX IF NOT EXISTS uq_meetings_source_record
        ON meetings (source_system, source_record_key)
    """))
    log.info("aprima copy meetings=%s lines=%s", copied_meetings, copied_lines)


def run_migration() -> None:
    if engine.dialect.name == "sqlite":
        return
    with engine.begin() as conn:
        apply(conn)
