"""Photo and warning tables for Send to Calendar.

SQLite tests create these from the models. Postgres creates them here.
"""

from sqlalchemy import text

from .database import engine


def run_migration():
    if engine.dialect.name == "sqlite":
        return
    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS fax_restore_sets (
                id SERIAL PRIMARY KEY,
                source_fax_id INTEGER NOT NULL UNIQUE
                    REFERENCES fax_documents(external_fax_id) ON DELETE CASCADE,
                run_id INTEGER REFERENCES fax_ingest_runs(id) ON DELETE SET NULL,
                created_at TIMESTAMP DEFAULT now(),
                restored_at TIMESTAMP
            )
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS fax_restore_lines (
                id SERIAL PRIMARY KEY,
                restore_set_id INTEGER NOT NULL
                    REFERENCES fax_restore_sets(id) ON DELETE CASCADE,
                schedule_card_activity_id INTEGER NOT NULL
                    REFERENCES schedule_card_activities(id) ON DELETE CASCADE,
                schedule_card_id INTEGER NOT NULL,
                surgeon_id INTEGER NOT NULL,
                location_id INTEGER,
                activity_date DATE NOT NULL,
                session VARCHAR(2) NOT NULL,
                activity_type VARCHAR(16) NOT NULL,
                start_time TIME,
                end_time TIME,
                patient_name VARCHAR(255) NOT NULL,
                procedure TEXT NOT NULL,
                room_text VARCHAR(128),
                source_system VARCHAR(32) NOT NULL,
                source_record_key VARCHAR(128) NOT NULL,
                identity_key VARCHAR(512) NOT NULL,
                fax_ingest_row_id INTEGER,
                aprima_appointment_id VARCHAR(36),
                is_active BOOLEAN NOT NULL,
                UNIQUE (restore_set_id, schedule_card_activity_id),
                CHECK (session IN ('am', 'pm')),
                CHECK (activity_type IN ('surgical', 'clinic'))
            )
        """))
        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS ix_fax_restore_lines_restore_set_id
            ON fax_restore_lines(restore_set_id)
        """))
        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS ix_fax_restore_lines_activity_id
            ON fax_restore_lines(schedule_card_activity_id)
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS schedule_warnings (
                id SERIAL PRIMARY KEY,
                warning_code VARCHAR(64) NOT NULL,
                schedule_card_id INTEGER NOT NULL
                    REFERENCES schedule_cards(id) ON DELETE CASCADE,
                source_fax_id INTEGER NOT NULL
                    REFERENCES fax_documents(external_fax_id) ON DELETE CASCADE,
                detail TEXT,
                created_at TIMESTAMP DEFAULT now(),
                UNIQUE (source_fax_id, schedule_card_id, warning_code)
            )
        """))
        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS ix_schedule_warnings_schedule_card_id
            ON schedule_warnings(schedule_card_id)
        """))
        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS ix_schedule_warnings_source_fax_id
            ON schedule_warnings(source_fax_id)
        """))
