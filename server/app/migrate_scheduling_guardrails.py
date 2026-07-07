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
                max_approved_off_per_day INTEGER NOT NULL DEFAULT 1,
                is_active BOOLEAN NOT NULL DEFAULT TRUE,
                created_at TIMESTAMP DEFAULT now()
            )
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
            INSERT INTO clinic_groups (name, abbreviation, max_approved_off_per_day, is_active)
            VALUES
                ('Winter Garden', 'WG', 2, TRUE),
                ('Lake Mary', 'LM', 1, TRUE)
            ON CONFLICT (name) DO NOTHING
        """))
