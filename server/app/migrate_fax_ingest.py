"""Fax ingest schema and database rules.

The AM/PM block schedule (schedule_cards) belongs to the
portal admin. Fax ingest only adds line items on top of it, and the database
enforces that: while a fax is being applied (cal.writer = 'fax_ingest'), any
write to the block tables is rejected, and cancelling a case is ignored when
that surgeon's day has a fax row that could not be applied. Fax rows whose
date/time has passed are never applied, and ingest cannot change past cases
or visits. Past-day cards and line items can never be deleted by anyone;
the portal admin may still correct them.
"""

from pathlib import Path

from sqlalchemy import text

from .database import engine

PRACTICE_TIMEZONE = "America/New_York"

APPLICABLE_VIEW_SELECT = """
    SELECT r.id AS fax_row_id, r.run_id
    FROM fax_ingest_rows r
    JOIN fax_row_decisions d ON d.fax_row_id = r.id
    JOIN schedule_cards c
      ON c.surgeon_id = r.surgeon_id
     AND c.date = r.case_date
     AND c.session = r.session
    WHERE COALESCE(r.extraction_flags, '') = ''
      AND d.status IN ('ready', 'ready_with_warning')
"""

# Anything on a fax whose date/time has already passed is ignored.
POSTGRES_APPLICABLE_VIEW_SELECT = (
    APPLICABLE_VIEW_SELECT
    + f"      AND r.case_date > CAST(now() AT TIME ZONE '{PRACTICE_TIMEZONE}' AS date)\n"
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
          AND (COALESCE(pd.source_received_at, pd.created_at), pd.external_fax_id, pr.id)
              < (COALESCE(cd.source_received_at, cd.created_at), cd.external_fax_id, cr.id)
        ORDER BY COALESCE(pd.source_received_at, pd.created_at) DESC,
                 pd.external_fax_id DESC, pr.id DESC
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
    resolution = Path(__file__).with_name("sql").joinpath("resolve_fax_candidates.sqlite.sql").read_text()
    from .fax_room_codes import seed_fax_room_codes
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS fax_room_codes (
            code VARCHAR(64) PRIMARY KEY,
            location_id INTEGER REFERENCES locations(id),
            kind VARCHAR(16) NOT NULL DEFAULT 'placeholder' CHECK (kind IN ('room', 'placeholder')),
            confirmed BOOLEAN NOT NULL DEFAULT 0,
            note TEXT
        )
    """))
    seed_fax_room_codes(conn)
    conn.execute(text(f"CREATE VIEW IF NOT EXISTS fax_ingest_candidate_resolutions AS {resolution}"))
    conn.execute(text(f"CREATE VIEW IF NOT EXISTS fax_ingest_rows_applicable AS {APPLICABLE_VIEW_SELECT}"))
    conn.execute(text("""
        CREATE TRIGGER IF NOT EXISTS fax_ingest_candidates_immutable_update
        BEFORE UPDATE ON fax_ingest_candidates
        BEGIN SELECT RAISE(ABORT, 'fax ingest candidates are immutable'); END
    """))
    conn.execute(text("""
        CREATE TRIGGER IF NOT EXISTS fax_ingest_candidates_immutable_delete
        BEFORE DELETE ON fax_ingest_candidates
        BEGIN SELECT RAISE(ABORT, 'fax ingest candidates are immutable'); END
    """))


def run_migration() -> None:
    if engine.dialect.name == "sqlite":
        return
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE fax_documents ADD COLUMN IF NOT EXISTS original_filename VARCHAR(255)"))
        conn.execute(text("ALTER TABLE fax_documents ADD COLUMN IF NOT EXISTS source_path TEXT"))
        conn.execute(text("ALTER TABLE fax_documents ADD COLUMN IF NOT EXISTS page_count INTEGER"))
        conn.execute(text("ALTER TABLE fax_documents ADD COLUMN IF NOT EXISTS source_received_at TIMESTAMPTZ"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_fax_documents_source_received_at ON fax_documents(source_received_at)"))
        conn.execute(text("ALTER TABLE fax_ingest_runs ADD COLUMN IF NOT EXISTS surgeon_scope_json TEXT NOT NULL DEFAULT '[]'"))
        conn.execute(text("ALTER TABLE fax_ingest_runs ADD COLUMN IF NOT EXISTS extractor_name VARCHAR(64) NOT NULL DEFAULT 'structured_extract'"))
        conn.execute(text("ALTER TABLE fax_ingest_runs ADD COLUMN IF NOT EXISTS extractor_version VARCHAR(64)"))
        conn.execute(text("ALTER TABLE fax_ingest_runs ADD COLUMN IF NOT EXISTS extractor_request_id VARCHAR(255)"))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS fax_ingest_candidates (
                id SERIAL PRIMARY KEY,
                run_id INTEGER NOT NULL REFERENCES fax_ingest_runs(id) ON DELETE CASCADE,
                page_number INTEGER NOT NULL,
                source_row_number INTEGER NOT NULL,
                surgeon_initials_raw VARCHAR(32) NOT NULL DEFAULT '',
                surgeon_name_raw VARCHAR(255),
                case_date_raw VARCHAR(32) NOT NULL,
                start_time_raw VARCHAR(32),
                row_type_raw VARCHAR(32) NOT NULL,
                room_raw VARCHAR(255) NOT NULL DEFAULT '',
                patient_name_raw VARCHAR(255) NOT NULL DEFAULT '',
                procedure_raw TEXT NOT NULL DEFAULT '',
                extraction_flags TEXT,
                evidence_ref TEXT,
                created_at TIMESTAMP DEFAULT now(),
                UNIQUE (run_id, page_number, source_row_number)
            )
        """))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_fax_ingest_candidates_run_id ON fax_ingest_candidates(run_id)"))
        conn.execute(text("""
            CREATE OR REPLACE FUNCTION cal_fax_candidates_immutable() RETURNS trigger AS $$
            BEGIN
              RAISE EXCEPTION 'fax ingest candidates are immutable';
            END
            $$ LANGUAGE plpgsql
        """))
        conn.execute(text("DROP TRIGGER IF EXISTS fax_ingest_candidates_immutable ON fax_ingest_candidates"))
        conn.execute(text("""
            CREATE TRIGGER fax_ingest_candidates_immutable
            BEFORE UPDATE OR DELETE ON fax_ingest_candidates
            FOR EACH ROW EXECUTE FUNCTION cal_fax_candidates_immutable()
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS fax_ingest_coverage (
                id SERIAL PRIMARY KEY,
                run_id INTEGER NOT NULL REFERENCES fax_ingest_runs(id) ON DELETE CASCADE,
                surgeon_id INTEGER NOT NULL REFERENCES surgeons(id),
                case_date DATE NOT NULL,
                created_at TIMESTAMP DEFAULT now(),
                UNIQUE (run_id, surgeon_id, case_date)
            )
        """))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_fax_ingest_coverage_run_id ON fax_ingest_coverage(run_id)"))
        conn.execute(text("ALTER TABLE fax_ingest_rows ADD COLUMN IF NOT EXISTS candidate_id INTEGER REFERENCES fax_ingest_candidates(id) ON DELETE CASCADE"))
        conn.execute(text("ALTER TABLE fax_ingest_rows ADD COLUMN IF NOT EXISTS source_row_number INTEGER NOT NULL DEFAULT 0"))
        conn.execute(text("""
            WITH numbered AS (
                SELECT id,
                       row_number() OVER (
                           PARTITION BY run_id, page_number
                           ORDER BY id
                       ) AS source_row_number
                FROM fax_ingest_rows
            )
            UPDATE fax_ingest_rows row
            SET source_row_number = numbered.source_row_number
            FROM numbered
            WHERE numbered.id = row.id
              AND row.source_row_number = 0
        """))
        conn.execute(text("""
            DO $$
            DECLARE constraint_name text;
            BEGIN
              FOR constraint_name IN
                SELECT con.conname
                FROM pg_constraint con
                JOIN pg_class rel ON rel.oid = con.conrelid
                WHERE rel.relname = 'fax_ingest_rows'
                  AND con.contype = 'u'
                  AND pg_get_constraintdef(con.oid) LIKE '%(run_id, normalized_key)%'
              LOOP
                EXECUTE format('ALTER TABLE fax_ingest_rows DROP CONSTRAINT %I', constraint_name);
              END LOOP;
            END $$
        """))
        conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS uq_fax_ingest_rows_candidate_id ON fax_ingest_rows(candidate_id) WHERE candidate_id IS NOT NULL"))
        conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS uq_fax_ingest_rows_source_row ON fax_ingest_rows(run_id, page_number, source_row_number)"))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS fax_room_codes (
                code VARCHAR(64) PRIMARY KEY,
                location_id INTEGER REFERENCES locations(id),
                kind VARCHAR(16) NOT NULL DEFAULT 'placeholder' CHECK (kind IN ('room', 'placeholder')),
                confirmed BOOLEAN NOT NULL DEFAULT FALSE,
                note TEXT
            )
        """))
        from .fax_room_codes import seed_fax_room_codes
        seed_fax_room_codes(conn)
        resolution = Path(__file__).with_name("sql").joinpath("resolve_fax_candidates.postgresql.sql").read_text()
        conn.execute(text("DROP VIEW IF EXISTS fax_ingest_candidate_resolutions"))
        conn.execute(text(f"CREATE VIEW fax_ingest_candidate_resolutions AS {resolution}"))
        old_list = conn.execute(text("SELECT to_regclass('public.surgical_cases')")).scalar()
        clinic_list = conn.execute(text("SELECT to_regclass('public.clinic_schedules')")).scalar()
        for statement in POSTGRES_RULES:
            if not old_list and "ON surgical_cases" in statement:
                continue
            if not clinic_list and "clinic_schedules" in statement:
                continue
            conn.execute(text(statement))
