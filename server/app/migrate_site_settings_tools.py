"""Idempotent site settings schema updates for optional admin tools."""

from sqlalchemy import text

from .database import engine


def run_migration():
    if engine.dialect.name == "sqlite":
        return

    with engine.begin() as conn:
        conn.execute(text("""
            ALTER TABLE site_settings
            ADD COLUMN IF NOT EXISTS show_or_patient_procedure_form BOOLEAN DEFAULT FALSE
        """))
