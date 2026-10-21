"""Remember the fax on the card line, then drop scratch rows that were already sent.

A staged reading stays. Send to Calendar is what throws that reading away.
"""

from sqlalchemy import text

from .database import engine


def _has_table(conn, name: str) -> bool:
    return conn.execute(text("SELECT to_regclass(:name)"), {"name": name}).scalar() is not None


def apply(conn) -> None:
    if not _has_table(conn, "schedule_card_activities"):
        return
    conn.execute(text("""
        DO $$ BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'schedule_card_activities'
                  AND column_name = 'source_record_key'
                  AND character_maximum_length < 640
            ) THEN
                ALTER TABLE schedule_card_activities
                    ALTER COLUMN source_record_key TYPE VARCHAR(640);
            END IF;
        END $$
    """))
    if _has_table(conn, "fax_restore_lines"):
        conn.execute(text("""
            DO $$ BEGIN
                IF EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_name = 'fax_restore_lines'
                      AND column_name = 'source_record_key'
                      AND character_maximum_length < 640
                ) THEN
                    ALTER TABLE fax_restore_lines
                        ALTER COLUMN source_record_key TYPE VARCHAR(640);
                END IF;
            END $$
        """))
        conn.execute(text("""
            ALTER TABLE fax_restore_lines
                ADD COLUMN IF NOT EXISTS source_fax_id INTEGER
        """))
        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS ix_fax_restore_lines_source_fax_id
            ON fax_restore_lines(source_fax_id)
        """))
    conn.execute(text("""
        ALTER TABLE schedule_card_activities
            ADD COLUMN IF NOT EXISTS source_fax_id INTEGER
    """))
    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS ix_schedule_card_activities_source_fax_id
        ON schedule_card_activities(source_fax_id)
    """))
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS fax_line_absences (
            id SERIAL PRIMARY KEY,
            schedule_card_activity_id INTEGER NOT NULL
                REFERENCES schedule_card_activities(id) ON DELETE CASCADE,
            run_id INTEGER NOT NULL REFERENCES fax_ingest_runs(id) ON DELETE CASCADE,
            created_at TIMESTAMP DEFAULT now(),
            UNIQUE (schedule_card_activity_id, run_id)
        )
    """))
    conn.execute(text("CREATE INDEX IF NOT EXISTS ix_fax_line_absences_activity_id ON fax_line_absences(schedule_card_activity_id)"))
    conn.execute(text("CREATE INDEX IF NOT EXISTS ix_fax_line_absences_run_id ON fax_line_absences(run_id)"))
    conn.execute(text("""
        UPDATE schedule_card_activities AS activity
        SET source_fax_id = document.external_fax_id
        FROM fax_ingest_rows AS fax_row
        JOIN fax_ingest_runs AS run ON run.id = fax_row.run_id
        JOIN fax_documents AS document ON document.id = run.fax_document_id
        WHERE activity.fax_ingest_row_id = fax_row.id
    """))
    conn.execute(text("""
        WITH candidates AS (
            SELECT
                activity.id AS activity_id,
                CAST(document.external_fax_id AS TEXT) || '|' || fax_row.normalized_key AS new_key,
                row_number() OVER (
                    PARTITION BY activity.source_system,
                                 CAST(document.external_fax_id AS TEXT) || '|' || fax_row.normalized_key
                    ORDER BY activity.is_active DESC, run.id DESC, activity.id DESC
                ) AS n
            FROM schedule_card_activities AS activity
            JOIN fax_ingest_rows AS fax_row ON fax_row.id = activity.fax_ingest_row_id
            JOIN fax_ingest_runs AS run ON run.id = fax_row.run_id
            JOIN fax_documents AS document ON document.id = run.fax_document_id
            WHERE activity.source_system = 'fax'
        )
        UPDATE schedule_card_activities AS activity
        SET source_record_key = candidates.new_key
        FROM candidates
        WHERE activity.id = candidates.activity_id
          AND candidates.n = 1
          AND activity.source_record_key IS DISTINCT FROM candidates.new_key
          AND NOT EXISTS (
              SELECT 1
              FROM schedule_card_activities AS other
              WHERE other.source_system = activity.source_system
                AND other.source_record_key = candidates.new_key
                AND other.id <> activity.id
          )
    """))
    conn.execute(text("""
        DELETE FROM fax_ingest_rows
        WHERE run_id IN (
            SELECT id FROM fax_ingest_runs WHERE status IN ('applied', 'restored')
        )
    """))


def run_migration() -> None:
    if engine.dialect.name == "sqlite":
        return
    with engine.begin() as conn:
        apply(conn)
