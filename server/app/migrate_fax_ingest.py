"""Fax ingest schema and database rules.

The AM/PM block schedule (schedule_cards, clinic_schedules) belongs to the
portal admin. Fax ingest only adds line items on top of it, and the database
enforces that: while a fax is being applied (cal.writer = 'fax_ingest'), any
write to the block tables is rejected, and cancelling a case is ignored when
that surgeon's day has a fax row that could not be applied. Fax rows whose
date/time has passed are never applied, and ingest cannot change past cases
or visits. Past-day cards and line items can never be deleted by anyone;
the portal admin may still correct them.
"""

from sqlalchemy import text

from .database import engine

PRACTICE_TIMEZONE = "America/New_York"

APPLICABLE_VIEW_SELECT = """
    SELECT r.id AS fax_row_id, r.run_id
    FROM fax_ingest_rows r
    JOIN schedule_cards c
      ON c.surgeon_id = r.surgeon_id
     AND c.date = r.case_date
     AND c.session = r.session
    WHERE COALESCE(r.extraction_flags, '') = ''
"""

# Anything on a fax whose date/time has already passed is ignored.
POSTGRES_APPLICABLE_VIEW_SELECT = (
    APPLICABLE_VIEW_SELECT
    + f"      AND r.case_date + COALESCE(r.start_time, time '00:00') > (now() AT TIME ZONE '{PRACTICE_TIMEZONE}')\n"
)

POSTGRES_RULES = [
    "ALTER TABLE fax_ingest_rows ADD COLUMN IF NOT EXISTS extraction_flags TEXT",
    f"CREATE OR REPLACE VIEW fax_ingest_rows_applicable AS {POSTGRES_APPLICABLE_VIEW_SELECT}",
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
    """
    CREATE OR REPLACE FUNCTION cal_cards_no_fax_stamp() RETURNS trigger AS $$
    BEGIN
        IF NEW.source LIKE 'fax:%' THEN
            RAISE EXCEPTION 'AM/PM cards are the permanent block schedule; fax ingest may not change them (source %)', NEW.source;
        END IF;
        RETURN NEW;
    END
    $$ LANGUAGE plpgsql
    """,
    "DROP TRIGGER IF EXISTS schedule_cards_no_fax_stamp ON schedule_cards",
    """
    CREATE TRIGGER schedule_cards_no_fax_stamp
    BEFORE INSERT OR UPDATE ON schedule_cards
    FOR EACH ROW EXECUTE FUNCTION cal_cards_no_fax_stamp()
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
    # A case is cancelled only when two faxes in a row leave it out.
    """
    CREATE OR REPLACE FUNCTION cal_cancel_needs_two_faxes() RETURNS trigger AS $$
    DECLARE
        current_run int := NULLIF(current_setting('cal.fax_run_id', true), '')::int;
        prev_run int;
    BEGIN
        IF COALESCE(current_setting('cal.writer', true), '') <> 'fax_ingest'
           OR NEW.status IS DISTINCT FROM 'cancelled'
           OR OLD.status IS NOT DISTINCT FROM 'cancelled'
        THEN
            RETURN NEW;
        END IF;
        SELECT pr.id INTO prev_run
        FROM fax_ingest_runs pr
        JOIN fax_documents pd ON pd.id = pr.fax_document_id
        JOIN fax_ingest_runs cr ON cr.id = current_run
        JOIN fax_documents cd ON cd.id = cr.fax_document_id
        WHERE pr.status = 'applied'
          AND pr.id <> cr.id
          AND pd.external_fax_id < cd.external_fax_id
        ORDER BY pd.external_fax_id DESC, pr.id DESC
        LIMIT 1;
        IF prev_run IS NULL
           OR NOT EXISTS (
               SELECT 1 FROM fax_ingest_rows x
               WHERE x.run_id = prev_run
               HAVING MIN(x.case_date) <= OLD.date AND MAX(x.case_date) >= OLD.date
           )
           OR EXISTS (
               SELECT 1 FROM fax_ingest_rows x
               WHERE x.run_id = prev_run
                 AND x.case_date = OLD.date
                 AND (x.surgeon_id IS NULL OR x.surgeon_id IN (OLD.surgeon_id, OLD.assisting_surgeon_id))
                 AND (
                     regexp_replace(lower(x.patient_name), '[^a-z0-9]', '', 'g')
                         = regexp_replace(lower(OLD.patient_name), '[^a-z0-9]', '', 'g')
                     OR (OLD.start_time IS NOT NULL AND x.start_time = OLD.start_time)
                 )
           )
        THEN
            RETURN OLD;
        END IF;
        RETURN NEW;
    END
    $$ LANGUAGE plpgsql
    """,
    "DROP TRIGGER IF EXISTS surgical_cases_cancel_needs_two_faxes ON surgical_cases",
    """
    CREATE TRIGGER surgical_cases_cancel_needs_two_faxes
    BEFORE UPDATE ON surgical_cases
    FOR EACH ROW EXECUTE FUNCTION cal_cancel_needs_two_faxes()
    """,
    f"""
    CREATE OR REPLACE FUNCTION cal_fax_cannot_touch_past_cases() RETURNS trigger AS $$
    BEGIN
        IF current_setting('cal.writer', true) = 'fax_ingest'
           AND OLD.date + COALESCE(OLD.start_time, time '00:00') <= (now() AT TIME ZONE '{PRACTICE_TIMEZONE}')
        THEN
            IF TG_OP = 'DELETE' THEN
                RETURN NULL;
            END IF;
            RETURN OLD;
        END IF;
        IF TG_OP = 'DELETE' THEN
            RETURN OLD;
        END IF;
        RETURN NEW;
    END
    $$ LANGUAGE plpgsql
    """,
    "DROP TRIGGER IF EXISTS surgical_cases_fax_cannot_touch_past ON surgical_cases",
    """
    CREATE TRIGGER surgical_cases_fax_cannot_touch_past
    BEFORE UPDATE OR DELETE ON surgical_cases
    FOR EACH ROW EXECUTE FUNCTION cal_fax_cannot_touch_past_cases()
    """,
    f"""
    CREATE OR REPLACE FUNCTION cal_fax_cannot_touch_past_activities() RETURNS trigger AS $$
    BEGIN
        IF current_setting('cal.writer', true) = 'fax_ingest'
           AND (CASE WHEN TG_OP = 'INSERT' THEN NEW.activity_date ELSE OLD.activity_date END)
               < (now() AT TIME ZONE '{PRACTICE_TIMEZONE}')::date
        THEN
            IF TG_OP = 'UPDATE' THEN
                RETURN OLD;
            END IF;
            RETURN NULL;
        END IF;
        IF TG_OP = 'DELETE' THEN
            RETURN OLD;
        END IF;
        RETURN NEW;
    END
    $$ LANGUAGE plpgsql
    """,
    "DROP TRIGGER IF EXISTS schedule_card_activities_fax_cannot_touch_past ON schedule_card_activities",
    """
    CREATE TRIGGER schedule_card_activities_fax_cannot_touch_past
    BEFORE INSERT OR UPDATE OR DELETE ON schedule_card_activities
    FOR EACH ROW EXECUTE FUNCTION cal_fax_cannot_touch_past_activities()
    """,
    # Past days are kept forever: nobody can delete a past AM/PM card or line item.
    f"""
    CREATE OR REPLACE FUNCTION cal_past_days_cannot_be_deleted() RETURNS trigger AS $$
    DECLARE
        row_day date := (to_jsonb(OLD) ->> TG_ARGV[0])::date;
    BEGIN
        IF row_day < (now() AT TIME ZONE '{PRACTICE_TIMEZONE}')::date THEN
            RAISE EXCEPTION 'Past days are locked: % row for % cannot be deleted', TG_TABLE_NAME, row_day
                USING ERRCODE = 'P0001', HINT = 'past_day_locked';
        END IF;
        RETURN OLD;
    END
    $$ LANGUAGE plpgsql
    """,
    *[
        statement
        for table, column in (
            ("schedule_cards", "date"),
            ("clinic_schedules", "date"),
            ("surgical_cases", "date"),
            ("schedule_card_activities", "activity_date"),
        )
        for statement in (
            f"DROP TRIGGER IF EXISTS {table}_past_days_cannot_be_deleted ON {table}",
            f"""
            CREATE TRIGGER {table}_past_days_cannot_be_deleted
            BEFORE DELETE ON {table}
            FOR EACH ROW EXECUTE FUNCTION cal_past_days_cannot_be_deleted('{column}')
            """,
        )
    ],
]


def create_applicable_view(conn) -> None:
    """SQLite (tests) gets the view without the passed-time rule; Postgres creates the full view in run_migration."""
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
