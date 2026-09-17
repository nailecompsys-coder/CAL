"""Schema migration for the permanent 10-card weekly schedule foundation."""

from sqlalchemy import text

from .database import engine


def run_migration() -> None:
    """Install PostgreSQL integrity checks after metadata creates the tables."""
    if engine.dialect.name == "sqlite":
        return
    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS schedule_card_weeks (
                id SERIAL PRIMARY KEY,
                surgeon_id INTEGER NOT NULL REFERENCES surgeons(id),
                week_start DATE NOT NULL,
                master_revision VARCHAR(64) NOT NULL DEFAULT 'master-v1',
                created_at TIMESTAMP DEFAULT now(),
                updated_at TIMESTAMP DEFAULT now(),
                CONSTRAINT uq_schedule_card_weeks_surgeon_week UNIQUE (surgeon_id, week_start)
            )
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS schedule_cards (
                id SERIAL PRIMARY KEY,
                week_id INTEGER NOT NULL REFERENCES schedule_card_weeks(id) ON DELETE CASCADE,
                surgeon_id INTEGER NOT NULL REFERENCES surgeons(id),
                date DATE NOT NULL,
                session VARCHAR(2) NOT NULL,
                baseline_state VARCHAR(16) NOT NULL,
                effective_state VARCHAR(16) NOT NULL,
                baseline_location_id INTEGER REFERENCES locations(id),
                effective_location_id INTEGER REFERENCES locations(id),
                master_template_id INTEGER REFERENCES surgeon_location_schedules(id),
                master_week_pattern VARCHAR(16) NOT NULL DEFAULT 'all',
                source VARCHAR(32) NOT NULL DEFAULT 'master',
                version INTEGER NOT NULL DEFAULT 1,
                created_at TIMESTAMP DEFAULT now(),
                updated_at TIMESTAMP DEFAULT now(),
                CONSTRAINT uq_schedule_cards_surgeon_date_session UNIQUE (surgeon_id, date, session),
                CONSTRAINT ck_schedule_cards_session CHECK (session IN ('am', 'pm')),
                CONSTRAINT ck_schedule_cards_baseline_state CHECK (baseline_state IN ('assigned', 'na', 'off')),
                CONSTRAINT ck_schedule_cards_effective_state CHECK (effective_state IN ('assigned', 'na', 'off')),
                CONSTRAINT ck_schedule_cards_baseline_location CHECK (baseline_state <> 'assigned' OR baseline_location_id IS NOT NULL),
                CONSTRAINT ck_schedule_cards_effective_location CHECK (effective_state <> 'assigned' OR effective_location_id IS NOT NULL)
            )
        """))
        conn.execute(text("""
            CREATE OR REPLACE FUNCTION assert_schedule_card_week_integrity()
            RETURNS trigger AS $$
            DECLARE
                target_week_id INTEGER;
                card_count INTEGER;
                day_count INTEGER;
            BEGIN
                target_week_id := COALESCE(NEW.week_id, OLD.week_id);
                IF NOT EXISTS (SELECT 1 FROM schedule_card_weeks WHERE id = target_week_id) THEN
                    RETURN NULL;
                END IF;
                SELECT COUNT(*), COUNT(DISTINCT date)
                INTO card_count, day_count
                FROM schedule_cards
                WHERE week_id = target_week_id;
                IF card_count <> 10 OR day_count <> 5 THEN
                    RAISE EXCEPTION 'schedule card week % must contain exactly 10 AM/PM cards', target_week_id;
                END IF;
                RETURN NULL;
            END;
            $$ LANGUAGE plpgsql;
        """))
        conn.execute(text("""
            DROP TRIGGER IF EXISTS schedule_card_week_integrity ON schedule_cards;
            CREATE CONSTRAINT TRIGGER schedule_card_week_integrity
            AFTER INSERT OR UPDATE OR DELETE ON schedule_cards
            DEFERRABLE INITIALLY DEFERRED
            FOR EACH ROW EXECUTE FUNCTION assert_schedule_card_week_integrity();
        """))
