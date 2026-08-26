"""Grok-BOT rules table + optional surgical case clock (fax rows with no time)."""

from sqlalchemy import text

from .database import engine


def run_migration():
    if engine.dialect.name == "sqlite":
        return
    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS grok_bot_rules (
                id SERIAL PRIMARY KEY,
                rule_id VARCHAR(64) NOT NULL UNIQUE,
                title VARCHAR(128) NOT NULL,
                instruction TEXT NOT NULL,
                handler VARCHAR(64) NOT NULL DEFAULT '',
                enabled BOOLEAN NOT NULL DEFAULT TRUE,
                is_builtin BOOLEAN NOT NULL DEFAULT FALSE,
                sort_order INTEGER NOT NULL DEFAULT 100,
                created_at TIMESTAMP DEFAULT now(),
                updated_at TIMESTAMP DEFAULT now()
            )
        """))
        conn.execute(text("""
            ALTER TABLE surgical_cases
            ALTER COLUMN start_time DROP NOT NULL
        """))
