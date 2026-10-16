"""A day-off link names the same surgeon as the request and the card."""

from sqlalchemy import text

from .database import engine


def apply(conn) -> None:
    conn.execute(text(
        "ALTER TABLE day_off_schedule_cards ADD COLUMN IF NOT EXISTS surgeon_id INTEGER"
    ))
    conn.execute(text("""
        DELETE FROM day_off_schedule_cards AS link
        WHERE NOT EXISTS (
            SELECT 1
            FROM days_off AS request
            JOIN schedule_cards AS card ON card.id = link.schedule_card_id
            WHERE request.id = link.day_off_id
              AND request.surgeon_id = card.surgeon_id
        )
    """))
    conn.execute(text("""
        UPDATE day_off_schedule_cards AS link
        SET surgeon_id = request.surgeon_id
        FROM days_off AS request
        WHERE link.day_off_id = request.id
          AND link.surgeon_id IS DISTINCT FROM request.surgeon_id
    """))
    conn.execute(text("DELETE FROM day_off_schedule_cards WHERE surgeon_id IS NULL"))
    conn.execute(text(
        "ALTER TABLE day_off_schedule_cards ALTER COLUMN surgeon_id SET NOT NULL"
    ))
    conn.execute(text("""
        DO $$ BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint WHERE conname = 'uq_days_off_id_surgeon'
            ) THEN
                ALTER TABLE days_off
                    ADD CONSTRAINT uq_days_off_id_surgeon UNIQUE (id, surgeon_id);
            END IF;
        END $$
    """))
    conn.execute(text("""
        DO $$ BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint WHERE conname = 'uq_schedule_cards_id_surgeon'
            ) THEN
                ALTER TABLE schedule_cards
                    ADD CONSTRAINT uq_schedule_cards_id_surgeon UNIQUE (id, surgeon_id);
            END IF;
        END $$
    """))
    conn.execute(text("""
        DO $$ BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint WHERE conname = 'fk_day_off_schedule_cards_day_off_surgeon'
            ) THEN
                ALTER TABLE day_off_schedule_cards
                    ADD CONSTRAINT fk_day_off_schedule_cards_day_off_surgeon
                    FOREIGN KEY (day_off_id, surgeon_id)
                    REFERENCES days_off (id, surgeon_id)
                    ON UPDATE CASCADE
                    ON DELETE CASCADE;
            END IF;
        END $$
    """))
    conn.execute(text("""
        DO $$ BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint WHERE conname = 'fk_day_off_schedule_cards_card_surgeon'
            ) THEN
                ALTER TABLE day_off_schedule_cards
                    ADD CONSTRAINT fk_day_off_schedule_cards_card_surgeon
                    FOREIGN KEY (schedule_card_id, surgeon_id)
                    REFERENCES schedule_cards (id, surgeon_id)
                    ON UPDATE CASCADE
                    ON DELETE CASCADE;
            END IF;
        END $$
    """))


def run_migration() -> None:
    if engine.dialect.name == "sqlite":
        return
    with engine.begin() as conn:
        apply(conn)
