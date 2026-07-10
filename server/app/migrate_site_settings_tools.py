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
        for col, ddl in (
            ("practice_address", "VARCHAR(255)"),
            ("practice_city", "VARCHAR(64)"),
            ("practice_state", "VARCHAR(32)"),
            ("practice_zip", "VARCHAR(16)"),
            ("practice_phone", "VARCHAR(32)"),
            ("practice_email", "VARCHAR(255)"),
        ):
            conn.execute(text(f"""
                ALTER TABLE site_settings
                ADD COLUMN IF NOT EXISTS {col} {ddl}
            """))
