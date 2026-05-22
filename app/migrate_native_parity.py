"""Idempotent native parity schema updates."""
from sqlalchemy import text

from .database import engine


def run_migration():
    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS call_coverages (
                id SERIAL PRIMARY KEY,
                call_rotation_id INTEGER NOT NULL REFERENCES call_rotations(id) ON DELETE CASCADE,
                original_surgeon_id INTEGER REFERENCES surgeons(id),
                covering_surgeon_id INTEGER NOT NULL REFERENCES surgeons(id),
                requested_by_surgeon_id INTEGER REFERENCES surgeons(id),
                status VARCHAR(16) DEFAULT 'active',
                notes TEXT,
                created_at TIMESTAMP DEFAULT now(),
                canceled_at TIMESTAMP
            )
        """))
        conn.execute(text("""
            CREATE UNIQUE INDEX IF NOT EXISTS ux_call_coverages_one_active
            ON call_coverages(call_rotation_id)
            WHERE status = 'active'
        """))
        conn.execute(text("""
            ALTER TABLE days_off
            ADD COLUMN IF NOT EXISTS start_time TIME
        """))
        conn.execute(text("""
            ALTER TABLE days_off
            ADD COLUMN IF NOT EXISTS end_time TIME
        """))
        conn.execute(text("""
            ALTER TABLE days_off
            ADD COLUMN IF NOT EXISTS is_full_day BOOLEAN DEFAULT TRUE
        """))
        conn.execute(text("""
            ALTER TABLE days_off
            ADD COLUMN IF NOT EXISTS segments TEXT
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS native_push_tokens (
                id SERIAL PRIMARY KEY,
                surgeon_id INTEGER NOT NULL REFERENCES surgeons(id) ON DELETE CASCADE,
                device_id INTEGER REFERENCES surgeon_devices(id),
                token TEXT NOT NULL UNIQUE,
                platform VARCHAR(32) DEFAULT 'ios',
                is_active BOOLEAN DEFAULT TRUE,
                created_at TIMESTAMP DEFAULT now(),
                updated_at TIMESTAMP
            )
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS native_schedule_alerts (
                id SERIAL PRIMARY KEY,
                surgeon_id INTEGER NOT NULL REFERENCES surgeons(id) ON DELETE CASCADE,
                title VARCHAR(255) NOT NULL,
                body TEXT NOT NULL,
                kind VARCHAR(64) DEFAULT 'schedule',
                payload TEXT,
                read_at TIMESTAMP,
                created_at TIMESTAMP DEFAULT now()
            )
        """))
        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS ix_native_schedule_alerts_surgeon_read_created
            ON native_schedule_alerts(surgeon_id, read_at, created_at DESC)
        """))
