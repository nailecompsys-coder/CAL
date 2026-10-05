"""Fax ingest schema and database rules.

The AM/PM block schedule (schedule_cards, clinic_schedules) belongs to the
portal admin. Fax ingest only adds line items on top of it, and the database
enforces that: while a fax is being applied (cal.writer = 'fax_ingest'), any
write to the block tables is rejected, and cancelling a case is ignored when
that surgeon's day has a fax row that could not be applied.
"""

from sqlalchemy import text

from .database import engine

APPLICABLE_VIEW_SELECT = """
    SELECT r.id AS fax_row_id, r.run_id
    FROM fax_ingest_rows r
    JOIN schedule_cards c
      ON c.surgeon_id = r.surgeon_id
     AND c.date = r.case_date
     AND c.session = r.session
    WHERE COALESCE(r.extraction_flags, '') = ''
"""

POSTGRES_RULES = [
    "ALTER TABLE fax_ingest_rows ADD COLUMN IF NOT EXISTS extraction_flags TEXT",
    f"CREATE OR REPLACE VIEW fax_ingest_rows_applicable AS {APPLICABLE_VIEW_SELECT}",
    """
    CREATE OR REPLACE FUNCTION cal_block_schedule_no_fax_writes() RETURNS trigger AS $$
    BEGIN
        IF current_setting('cal.writer', true) = 'fax_ingest' THEN
            RAISE EXCEPTION '% is the permanent block schedule; fax ingest may not change it', TG_TABLE_NAME;
        END IF;
        IF TG_OP = 'DELETE' THEN
            RETURN OLD;
        END IF;
        RETURN NEW;
    END
    $$ LANGUAGE plpgsql
    """,
    "DROP TRIGGER IF EXISTS schedule_cards_no_fax_writes ON schedule_cards",
    """
    CREATE TRIGGER schedule_cards_no_fax_writes
    BEFORE INSERT OR UPDATE OR DELETE ON schedule_cards
    FOR EACH ROW EXECUTE FUNCTION cal_block_schedule_no_fax_writes()
    """,
    "DROP TRIGGER IF EXISTS clinic_schedules_no_fax_writes ON clinic_schedules",
    """
    CREATE TRIGGER clinic_schedules_no_fax_writes
    BEFORE INSERT OR UPDATE OR DELETE ON clinic_schedules
    FOR EACH ROW EXECUTE FUNCTION cal_block_schedule_no_fax_writes()
    """,
    """
    CREATE OR REPLACE FUNCTION cal_keep_cases_on_unapplied_fax_days() RETURNS trigger AS $$
    BEGIN
        IF current_setting('cal.writer', true) = 'fax_ingest'
           AND NEW.status = 'cancelled'
           AND OLD.status IS DISTINCT FROM 'cancelled'
           AND EXISTS (
               SELECT 1
               FROM fax_ingest_rows r
               WHERE r.run_id = NULLIF(current_setting('cal.fax_run_id', true), '')::int
                 AND r.case_date = OLD.date
                 AND (r.surgeon_id IS NULL OR r.surgeon_id IN (OLD.surgeon_id, OLD.assisting_surgeon_id))
                 AND NOT EXISTS (
                     SELECT 1 FROM fax_ingest_rows_applicable a WHERE a.fax_row_id = r.id
                 )
           )
        THEN
            RETURN OLD;
        END IF;
        RETURN NEW;
    END
    $$ LANGUAGE plpgsql
    """,
    "DROP TRIGGER IF EXISTS surgical_cases_keep_on_unapplied_fax_days ON surgical_cases",
    """
    CREATE TRIGGER surgical_cases_keep_on_unapplied_fax_days
    BEFORE UPDATE ON surgical_cases
    FOR EACH ROW EXECUTE FUNCTION cal_keep_cases_on_unapplied_fax_days()
    """,
]


def create_applicable_view(conn) -> None:
    """SQLite (tests) gets the same view; Postgres creates it in run_migration."""
    conn.execute(text(f"CREATE VIEW IF NOT EXISTS fax_ingest_rows_applicable AS {APPLICABLE_VIEW_SELECT}"))


def run_migration() -> None:
    if engine.dialect.name == "sqlite":
        return
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE fax_documents ADD COLUMN IF NOT EXISTS original_filename VARCHAR(255)"))
        conn.execute(text("ALTER TABLE fax_documents ADD COLUMN IF NOT EXISTS source_path TEXT"))
        conn.execute(text("ALTER TABLE fax_documents ADD COLUMN IF NOT EXISTS page_count INTEGER"))
        conn.execute(text("ALTER TABLE fax_ingest_runs ADD COLUMN IF NOT EXISTS surgeon_scope_json TEXT NOT NULL DEFAULT '[]'"))
        for statement in POSTGRES_RULES:
            conn.execute(text(statement))
