"""Normalize production schedule activity fields used by SQL totals."""

from sqlalchemy import text

from .database import engine


def run_migration() -> None:
    if engine.dialect.name == "sqlite":
        return
    with engine.begin() as conn:
        conn.execute(text("""
            DO $$ BEGIN
                IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'uq_call_rotations_date_group') THEN
                    ALTER TABLE call_rotations
                    ADD CONSTRAINT uq_call_rotations_date_group UNIQUE (date, call_group_id);
                END IF;
            END $$
        """))
        conn.execute(text("""
            DO $$ BEGIN
                IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'uq_fax_ingest_rows_run_normalized_key') THEN
                    ALTER TABLE fax_ingest_rows
                    ADD CONSTRAINT uq_fax_ingest_rows_run_normalized_key UNIQUE (run_id, normalized_key);
                END IF;
            END $$
        """))
        conn.execute(text("ALTER TABLE surgical_cases ADD COLUMN IF NOT EXISTS schedule_card_id INTEGER REFERENCES schedule_cards(id)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_surgical_cases_schedule_card_id ON surgical_cases(schedule_card_id)"))
        for ddl in (
            "ALTER TABLE aprima_cached_appointments ADD COLUMN IF NOT EXISTS surgeon_id INTEGER REFERENCES surgeons(id)",
            "ALTER TABLE aprima_cached_appointments ADD COLUMN IF NOT EXISTS location_id INTEGER REFERENCES locations(id)",
            "ALTER TABLE aprima_cached_appointments ADD COLUMN IF NOT EXISTS schedule_card_id INTEGER REFERENCES schedule_cards(id)",
            "ALTER TABLE aprima_cached_appointments ADD COLUMN IF NOT EXISTS session VARCHAR(2)",
            "ALTER TABLE aprima_cached_appointments ADD COLUMN IF NOT EXISTS start_time TIME",
            "ALTER TABLE aprima_cached_appointments ADD COLUMN IF NOT EXISTS end_time TIME",
            "ALTER TABLE aprima_cached_appointments ADD COLUMN IF NOT EXISTS patient_name VARCHAR(255)",
            "ALTER TABLE aprima_cached_appointments ADD COLUMN IF NOT EXISTS activity_type VARCHAR(16)",
            "ALTER TABLE aprima_cached_appointments ADD COLUMN IF NOT EXISTS room_text VARCHAR(128)",
            "ALTER TABLE aprima_cached_appointments ADD COLUMN IF NOT EXISTS service_site VARCHAR(255)",
            "ALTER TABLE aprima_cached_appointments ADD COLUMN IF NOT EXISTS appointment_type VARCHAR(255)",
            "ALTER TABLE aprima_cached_appointments ADD COLUMN IF NOT EXISTS reason_text TEXT",
        ):
            conn.execute(text(ddl))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS call_daily_assignments (
                id SERIAL PRIMARY KEY,
                date DATE NOT NULL,
                location_id INTEGER NOT NULL REFERENCES locations(id),
                surgeon_id INTEGER NOT NULL REFERENCES surgeons(id),
                call_group_id INTEGER NOT NULL REFERENCES call_groups(id),
                call_rotation_id INTEGER NOT NULL REFERENCES call_rotations(id) ON DELETE CASCADE,
                call_coverage_id INTEGER REFERENCES call_coverages(id) ON DELETE SET NULL,
                original_surgeon_id INTEGER REFERENCES surgeons(id),
                created_at TIMESTAMP DEFAULT now(),
                updated_at TIMESTAMP DEFAULT now(),
                CONSTRAINT uq_call_daily_assignment_date_location UNIQUE (date, location_id)
            )
        """))
        for ddl in (
            "CREATE INDEX IF NOT EXISTS ix_call_daily_assignments_date ON call_daily_assignments(date)",
            "CREATE INDEX IF NOT EXISTS ix_call_daily_assignments_location_id ON call_daily_assignments(location_id)",
            "CREATE INDEX IF NOT EXISTS ix_call_daily_assignments_surgeon_id ON call_daily_assignments(surgeon_id)",
            "CREATE INDEX IF NOT EXISTS ix_call_daily_assignments_call_group_id ON call_daily_assignments(call_group_id)",
            "CREATE INDEX IF NOT EXISTS ix_call_daily_assignments_call_rotation_id ON call_daily_assignments(call_rotation_id)",
            "CREATE INDEX IF NOT EXISTS ix_call_daily_assignments_call_coverage_id ON call_daily_assignments(call_coverage_id)",
        ):
            conn.execute(text(ddl))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_aprima_cached_appointments_surgeon_id ON aprima_cached_appointments(surgeon_id)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_aprima_cached_appointments_location_id ON aprima_cached_appointments(location_id)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_aprima_cached_appointments_schedule_card_id ON aprima_cached_appointments(schedule_card_id)"))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS day_off_schedule_cards (
                id SERIAL PRIMARY KEY,
                day_off_id INTEGER NOT NULL REFERENCES days_off(id) ON DELETE CASCADE,
                schedule_card_id INTEGER NOT NULL REFERENCES schedule_cards(id) ON DELETE CASCADE,
                created_at TIMESTAMP DEFAULT now(),
                CONSTRAINT uq_day_off_schedule_cards UNIQUE (day_off_id, schedule_card_id)
            )
        """))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_day_off_schedule_cards_day_off_id ON day_off_schedule_cards(day_off_id)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_day_off_schedule_cards_schedule_card_id ON day_off_schedule_cards(schedule_card_id)"))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS schedule_card_activities (
                id SERIAL PRIMARY KEY,
                schedule_card_id INTEGER NOT NULL REFERENCES schedule_cards(id) ON DELETE CASCADE,
                surgeon_id INTEGER NOT NULL REFERENCES surgeons(id),
                location_id INTEGER REFERENCES locations(id),
                activity_date DATE NOT NULL,
                session VARCHAR(2) NOT NULL CHECK (session IN ('am', 'pm')),
                activity_type VARCHAR(16) NOT NULL CHECK (activity_type IN ('surgical', 'clinic')),
                start_time TIME,
                end_time TIME,
                patient_name VARCHAR(255) NOT NULL,
                procedure TEXT NOT NULL DEFAULT '',
                room_text VARCHAR(128),
                source_system VARCHAR(32) NOT NULL,
                source_record_key VARCHAR(128) NOT NULL,
                surgical_case_id INTEGER REFERENCES surgical_cases(id) ON DELETE SET NULL,
                fax_ingest_row_id INTEGER REFERENCES fax_ingest_rows(id) ON DELETE SET NULL,
                aprima_appointment_id VARCHAR(36) REFERENCES aprima_cached_appointments(appointment_id) ON DELETE SET NULL,
                identity_key VARCHAR(512) NOT NULL,
                is_active BOOLEAN NOT NULL DEFAULT TRUE,
                created_at TIMESTAMP DEFAULT now(),
                updated_at TIMESTAMP DEFAULT now(),
                CONSTRAINT uq_schedule_card_activity_source UNIQUE (source_system, source_record_key)
            )
        """))
        for ddl in (
            "ALTER TABLE schedule_card_activities ADD COLUMN IF NOT EXISTS end_time TIME",
            "ALTER TABLE schedule_card_activities ADD COLUMN IF NOT EXISTS surgical_case_id INTEGER REFERENCES surgical_cases(id) ON DELETE SET NULL",
            "ALTER TABLE schedule_card_activities ADD COLUMN IF NOT EXISTS fax_ingest_row_id INTEGER REFERENCES fax_ingest_rows(id) ON DELETE SET NULL",
            "ALTER TABLE schedule_card_activities ADD COLUMN IF NOT EXISTS aprima_appointment_id VARCHAR(36) REFERENCES aprima_cached_appointments(appointment_id) ON DELETE SET NULL",
            "CREATE INDEX IF NOT EXISTS ix_schedule_card_activities_schedule_card_id ON schedule_card_activities(schedule_card_id)",
            "CREATE INDEX IF NOT EXISTS ix_schedule_card_activities_surgeon_id ON schedule_card_activities(surgeon_id)",
            "CREATE INDEX IF NOT EXISTS ix_schedule_card_activities_location_id ON schedule_card_activities(location_id)",
            "CREATE INDEX IF NOT EXISTS ix_schedule_card_activities_activity_date ON schedule_card_activities(activity_date)",
            "CREATE INDEX IF NOT EXISTS ix_schedule_card_activities_identity_key ON schedule_card_activities(identity_key)",
            "CREATE INDEX IF NOT EXISTS ix_schedule_card_activities_is_active ON schedule_card_activities(is_active)",
            "CREATE INDEX IF NOT EXISTS ix_schedule_card_activities_surgical_case_id ON schedule_card_activities(surgical_case_id)",
            "CREATE INDEX IF NOT EXISTS ix_schedule_card_activities_fax_ingest_row_id ON schedule_card_activities(fax_ingest_row_id)",
            "CREATE INDEX IF NOT EXISTS ix_schedule_card_activities_aprima_appointment_id ON schedule_card_activities(aprima_appointment_id)",
        ):
            conn.execute(text(ddl))
        _keep_card_as_only_deleting_parent(conn)
        _line_identity_matches_card(conn)


def _keep_card_as_only_deleting_parent(conn) -> None:
    """A source row may disappear. That must not delete the card line."""
    parents = (
        (
            "surgical_case_id",
            "schedule_card_activities_surgical_case_id_fkey",
            "FOREIGN KEY (surgical_case_id) REFERENCES surgical_cases(id) ON DELETE SET NULL",
        ),
        (
            "fax_ingest_row_id",
            "schedule_card_activities_fax_ingest_row_id_fkey",
            "FOREIGN KEY (fax_ingest_row_id) REFERENCES fax_ingest_rows(id) ON DELETE SET NULL",
        ),
        (
            "aprima_appointment_id",
            "schedule_card_activities_aprima_appointment_id_fkey",
            "FOREIGN KEY (aprima_appointment_id) REFERENCES aprima_cached_appointments(appointment_id) ON DELETE SET NULL",
        ),
    )
    for column, constraint_name, definition in parents:
        conn.execute(text(f"""
            DO $$
            DECLARE
              bad_name text;
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
                  AND att.attname = '{column}'
                  AND con.confdeltype IS DISTINCT FROM 'n'
              LOOP
                EXECUTE format('ALTER TABLE schedule_card_activities DROP CONSTRAINT %I', bad_name);
              END LOOP;
              IF NOT EXISTS (
                SELECT 1
                FROM pg_constraint con
                JOIN pg_class rel ON rel.oid = con.conrelid
                JOIN pg_attribute att
                  ON att.attrelid = rel.oid
                 AND att.attnum = ANY (con.conkey)
                WHERE rel.relname = 'schedule_card_activities'
                  AND con.contype = 'f'
                  AND att.attname = '{column}'
                  AND con.confdeltype = 'n'
              ) THEN
                ALTER TABLE schedule_card_activities
                  ADD CONSTRAINT {constraint_name} {definition};
              END IF;
            END $$
        """))


def _line_identity_matches_card(conn) -> None:
    """A line's surgeon, date, and half-day are the card's. Copy any drift, then lock it."""
    conn.execute(text("""
        UPDATE schedule_card_activities AS activity
        SET surgeon_id = card.surgeon_id,
            activity_date = card.date,
            session = card.session
        FROM schedule_cards AS card
        WHERE activity.schedule_card_id = card.id
          AND (
              activity.surgeon_id IS DISTINCT FROM card.surgeon_id
              OR activity.activity_date IS DISTINCT FROM card.date
              OR activity.session IS DISTINCT FROM card.session
          )
    """))
    conn.execute(text("""
        DO $$ BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint WHERE conname = 'uq_schedule_cards_identity'
            ) THEN
                ALTER TABLE schedule_cards
                    ADD CONSTRAINT uq_schedule_cards_identity
                    UNIQUE (id, surgeon_id, date, session);
            END IF;
        END $$
    """))
    conn.execute(text("""
        DO $$ BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint WHERE conname = 'fk_schedule_card_activities_card_identity'
            ) THEN
                ALTER TABLE schedule_card_activities
                    ADD CONSTRAINT fk_schedule_card_activities_card_identity
                    FOREIGN KEY (schedule_card_id, surgeon_id, activity_date, session)
                    REFERENCES schedule_cards (id, surgeon_id, date, session)
                    ON UPDATE CASCADE
                    ON DELETE CASCADE;
            END IF;
        END $$
    """))
