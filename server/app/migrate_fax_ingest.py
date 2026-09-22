"""Add immutable fax source metadata to installations created before fax staging v2."""

from sqlalchemy import text

from .database import engine


def run_migration() -> None:
    if engine.dialect.name == "sqlite":
        return
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE fax_documents ADD COLUMN IF NOT EXISTS original_filename VARCHAR(255)"))
        conn.execute(text("ALTER TABLE fax_documents ADD COLUMN IF NOT EXISTS source_path TEXT"))
        conn.execute(text("ALTER TABLE fax_documents ADD COLUMN IF NOT EXISTS page_count INTEGER"))
