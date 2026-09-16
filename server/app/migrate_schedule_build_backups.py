from sqlalchemy import text

from .database import engine


def run_migration():
    if engine.dialect.name == "sqlite":
        return
    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS schedule_build_backups (
                id SERIAL PRIMARY KEY,
                start_date DATE NOT NULL,
                end_date DATE NOT NULL,
                payload_json TEXT NOT NULL,
                created_by_admin_id INTEGER REFERENCES admin_users(id),
                created_at TIMESTAMP DEFAULT now(),
                reverted_by_admin_id INTEGER REFERENCES admin_users(id),
                reverted_at TIMESTAMP,
                note TEXT
            )
        """))
        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS ix_schedule_build_backups_dates
            ON schedule_build_backups(start_date, end_date)
        """))
