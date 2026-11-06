"""Add a nullable text MRN to fax lines.

Additive only. Existing rows stay NULL until a later fax fills them.
The column is TEXT so a value such as 00123456 keeps its leading zeros.
"""

from sqlalchemy import text

from .database import engine

# (table, index name or None). The line table is the one RVU and the hernia
# tracker look up. Staging tables carry the same value until the line is written.
# The restore photo keeps it so Send-to-Calendar undo puts the old value back.
_MRN_COLUMNS = (
    ("fax_ingest_candidates", "ix_fax_ingest_candidates_mrn"),
    ("fax_ingest_rows", "ix_fax_ingest_rows_mrn"),
    ("schedule_card_activities", "ix_schedule_card_activities_mrn"),
    ("fax_restore_lines", None),
)


def ensure_mrn_columns(conn) -> None:
    """Add mrn TEXT to tables that already exist. Safe to run more than once."""
    for table, index_name in _MRN_COLUMNS:
        if conn.execute(
            text("SELECT to_regclass(:name)"),
            {"name": f"public.{table}"},
        ).scalar() is None:
            continue
        conn.execute(text(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS mrn TEXT"))
        if index_name:
            conn.execute(text(
                f"CREATE INDEX IF NOT EXISTS {index_name} ON {table} (mrn)"
            ))


def run_migration() -> None:
    if engine.dialect.name == "sqlite":
        return
    with engine.begin() as conn:
        ensure_mrn_columns(conn)
