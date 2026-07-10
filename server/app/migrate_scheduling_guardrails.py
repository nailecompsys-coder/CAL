"""Idempotent scheduling guardrail schema updates."""

from sqlalchemy import text

from .database import engine


def run_migration():
    if engine.dialect.name == "sqlite":
        return

    with engine.begin() as conn:
        conn.execute(text("""
            ALTER TABLE days_off
            ADD COLUMN IF NOT EXISTS review_findings TEXT
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS clinic_groups (
                id SERIAL PRIMARY KEY,
                name VARCHAR(128) NOT NULL UNIQUE,
                abbreviation VARCHAR(12) NOT NULL,
                group_type VARCHAR(16) NOT NULL DEFAULT 'people',
                enforce_day_off_limit BOOLEAN NOT NULL DEFAULT FALSE,
                max_approved_off_per_day INTEGER NOT NULL DEFAULT 1,
                is_active BOOLEAN NOT NULL DEFAULT TRUE,
                created_at TIMESTAMP DEFAULT now()
            )
        """))
        conn.execute(text("""
            ALTER TABLE clinic_groups
            ADD COLUMN IF NOT EXISTS group_type VARCHAR(16) NOT NULL DEFAULT 'people'
        """))
        conn.execute(text("""
            ALTER TABLE clinic_groups
            ADD COLUMN IF NOT EXISTS enforce_day_off_limit BOOLEAN NOT NULL DEFAULT FALSE
        """))
        # Existing seeded capacity groups keep day-off enforcement on.
        conn.execute(text("""
            UPDATE clinic_groups
            SET enforce_day_off_limit = TRUE
            WHERE name IN ('Winter Garden', 'Lake Mary')
              AND COALESCE(enforce_day_off_limit, FALSE) = FALSE
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS clinic_group_members (
                id SERIAL PRIMARY KEY,
                clinic_group_id INTEGER NOT NULL REFERENCES clinic_groups(id) ON DELETE CASCADE,
                surgeon_id INTEGER NOT NULL REFERENCES surgeons(id) ON DELETE CASCADE,
                UNIQUE (clinic_group_id, surgeon_id)
            )
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS clinic_group_locations (
                id SERIAL PRIMARY KEY,
                clinic_group_id INTEGER NOT NULL REFERENCES clinic_groups(id) ON DELETE CASCADE,
                location_id INTEGER NOT NULL REFERENCES locations(id) ON DELETE CASCADE,
                UNIQUE (clinic_group_id, location_id)
            )
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS surgical_blocks (
                id SERIAL PRIMARY KEY,
                surgeon_id INTEGER NOT NULL REFERENCES surgeons(id) ON DELETE CASCADE,
                location_id INTEGER REFERENCES locations(id),
                day_of_week INTEGER,
                block_date DATE,
                start_time TIME NOT NULL,
                end_time TIME NOT NULL,
                recurrence VARCHAR(16) DEFAULT 'weekly',
                is_active BOOLEAN NOT NULL DEFAULT TRUE,
                notes TEXT,
                created_at TIMESTAMP DEFAULT now()
            )
        """))
        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS ix_surgical_blocks_surgeon_weekday
            ON surgical_blocks(surgeon_id, day_of_week)
        """))
        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS ix_surgical_blocks_surgeon_date
            ON surgical_blocks(surgeon_id, block_date)
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS or_block_series (
                id SERIAL PRIMARY KEY,
                name VARCHAR(128) NOT NULL,
                recurrence VARCHAR(16) DEFAULT 'weekly',
                weekday INTEGER,
                start_date DATE NOT NULL,
                end_date DATE NOT NULL,
                session VARCHAR(16) DEFAULT 'am',
                start_time TIME NOT NULL,
                end_time TIME NOT NULL,
                owner_type VARCHAR(16) DEFAULT 'practice',
                owner_surgeon_id INTEGER REFERENCES surgeons(id),
                release_policy_days INTEGER DEFAULT 3,
                is_active BOOLEAN NOT NULL DEFAULT TRUE,
                notes TEXT,
                created_by_admin_id INTEGER REFERENCES admin_users(id),
                created_at TIMESTAMP DEFAULT now(),
                updated_at TIMESTAMP
            )
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS or_block_instances (
                id SERIAL PRIMARY KEY,
                series_id INTEGER REFERENCES or_block_series(id) ON DELETE CASCADE,
                location_id INTEGER NOT NULL REFERENCES locations(id),
                date DATE NOT NULL,
                session VARCHAR(16) DEFAULT 'am',
                start_time TIME NOT NULL,
                end_time TIME NOT NULL,
                status VARCHAR(24) DEFAULT 'open',
                assigned_surgeon_id INTEGER REFERENCES surgeons(id),
                assigned_by_admin_id INTEGER REFERENCES admin_users(id),
                assigned_at TIMESTAMP,
                assigned_start_time TIME,
                assigned_case_count INTEGER,
                assignment_note TEXT,
                release_deadline TIMESTAMP,
                released_at TIMESTAMP,
                released_by_admin_id INTEGER REFERENCES admin_users(id),
                release_reason TEXT,
                advent_report_status VARCHAR(24) DEFAULT 'not_sent',
                notes TEXT,
                created_at TIMESTAMP DEFAULT now(),
                updated_at TIMESTAMP
            )
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS or_block_audit_events (
                id SERIAL PRIMARY KEY,
                block_instance_id INTEGER NOT NULL REFERENCES or_block_instances(id) ON DELETE CASCADE,
                admin_user_id INTEGER REFERENCES admin_users(id),
                event_type VARCHAR(32) NOT NULL,
                detail TEXT,
                created_at TIMESTAMP DEFAULT now()
            )
        """))
        conn.execute(text("""
            ALTER TABLE or_block_instances
            ADD COLUMN IF NOT EXISTS assigned_start_time TIME
        """))
        conn.execute(text("""
            ALTER TABLE or_block_instances
            ADD COLUMN IF NOT EXISTS assigned_case_count INTEGER
        """))
        conn.execute(text("""
            ALTER TABLE or_block_instances
            ADD COLUMN IF NOT EXISTS assignment_note TEXT
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS or_block_assignments (
                id SERIAL PRIMARY KEY,
                block_instance_id INTEGER NOT NULL REFERENCES or_block_instances(id) ON DELETE CASCADE,
                surgeon_id INTEGER NOT NULL REFERENCES surgeons(id),
                assigned_by_admin_id INTEGER REFERENCES admin_users(id),
                start_time TIME NOT NULL,
                case_count INTEGER DEFAULT 1,
                note TEXT,
                created_at TIMESTAMP DEFAULT now(),
                updated_at TIMESTAMP
            )
        """))
        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS ix_or_block_assignments_block_time
            ON or_block_assignments(block_instance_id, start_time)
        """))
        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS ix_or_block_assignments_surgeon
            ON or_block_assignments(surgeon_id, start_time)
        """))
        conn.execute(text("""
            INSERT INTO or_block_assignments (
                block_instance_id,
                surgeon_id,
                assigned_by_admin_id,
                start_time,
                case_count,
                note,
                created_at
            )
            SELECT
                obi.id,
                obi.assigned_surgeon_id,
                obi.assigned_by_admin_id,
                COALESCE(obi.assigned_start_time, obi.start_time),
                COALESCE(NULLIF(obi.assigned_case_count, 0), 1),
                obi.assignment_note,
                COALESCE(obi.assigned_at, obi.created_at, now())
            FROM or_block_instances obi
            WHERE obi.assigned_surgeon_id IS NOT NULL
              AND NOT EXISTS (
                SELECT 1 FROM or_block_assignments oba
                WHERE oba.block_instance_id = obi.id
                  AND oba.surgeon_id = obi.assigned_surgeon_id
                  AND oba.start_time = COALESCE(obi.assigned_start_time, obi.start_time)
              )
        """))
        conn.execute(text("""
            ALTER TABLE surgical_cases
            ADD COLUMN IF NOT EXISTS or_block_instance_id INTEGER REFERENCES or_block_instances(id)
        """))
        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS ix_or_block_instances_date_location
            ON or_block_instances(date, location_id)
        """))
        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS ix_or_block_instances_status_date
            ON or_block_instances(status, date)
        """))
        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS ix_or_block_instances_assigned_surgeon
            ON or_block_instances(assigned_surgeon_id, date)
        """))
        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS ix_surgical_cases_or_block_instance
            ON surgical_cases(or_block_instance_id)
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS admin_otp_challenges (
                id SERIAL PRIMARY KEY,
                admin_user_id INTEGER NOT NULL REFERENCES admin_users(id) ON DELETE CASCADE,
                token_hash VARCHAR(255) NOT NULL,
                expires_at TIMESTAMP NOT NULL,
                used_at TIMESTAMP,
                created_at TIMESTAMP DEFAULT now()
            )
        """))
        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS ix_admin_otp_challenges_admin
            ON admin_otp_challenges(admin_user_id, expires_at)
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS schedule_change_events (
                id SERIAL PRIMARY KEY,
                event_type VARCHAR(64) NOT NULL,
                surgeon_id INTEGER REFERENCES surgeons(id),
                admin_user_id INTEGER REFERENCES admin_users(id),
                date DATE,
                title VARCHAR(255) NOT NULL,
                body TEXT,
                payload TEXT,
                created_at TIMESTAMP DEFAULT now()
            )
        """))
        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS ix_schedule_change_events_created
            ON schedule_change_events(created_at)
        """))
        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS ix_schedule_change_events_date
            ON schedule_change_events(date)
        """))
        conn.execute(text("""
            INSERT INTO clinic_groups (
                name, abbreviation, group_type, enforce_day_off_limit, max_approved_off_per_day, is_active
            )
            VALUES
                ('Winter Garden', 'WG', 'people', TRUE, 2, TRUE),
                ('Lake Mary', 'LM', 'people', TRUE, 1, TRUE)
            ON CONFLICT (name) DO NOTHING
        """))
