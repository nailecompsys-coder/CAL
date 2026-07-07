from sqlalchemy import text

from .database import engine


def run_migration():
    if engine.dialect.name == "sqlite":
        return
    with engine.begin() as conn:
        conn.execute(text("""
            ALTER TABLE clinic_schedules
            ADD COLUMN IF NOT EXISTS assignment_type VARCHAR(16) NOT NULL DEFAULT 'assigned'
        """))
        conn.execute(text("""
            ALTER TABLE clinic_schedules
            ALTER COLUMN location_id DROP NOT NULL
        """))
        conn.execute(text("""
            UPDATE clinic_schedules
            SET assignment_type = 'assigned'
            WHERE assignment_type IS NULL OR assignment_type = ''
        """))
