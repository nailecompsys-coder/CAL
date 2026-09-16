from sqlalchemy import text

from .database import engine


def run_migration():
    if engine.dialect.name == "sqlite":
        return
    with engine.begin() as conn:
        conn.execute(text("""
            ALTER TABLE surgeon_location_schedules
            ADD COLUMN IF NOT EXISTS week_pattern VARCHAR(16) NOT NULL DEFAULT 'all'
        """))
        conn.execute(text("""
            UPDATE surgeon_location_schedules
            SET week_pattern = 'all'
            WHERE week_pattern IS NULL OR week_pattern = ''
        """))
