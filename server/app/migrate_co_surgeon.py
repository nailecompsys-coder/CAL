"""Co-surgeon (assisting surgeon) schema + seed.

Adds:
- surgical_cases.assisting_surgeon_id
- co_surgeon_pairs (directional primary -> assisting rule)

Seeds the known recurring pair: Dr. Florin (primary) assisted by Dr. Froehling.
Idempotent; safe to run on every boot.
"""

from sqlalchemy import text

from .database import engine


def run_migration():
    if engine.dialect.name == "sqlite":
        return

    with engine.begin() as conn:
        conn.execute(text("""
            ALTER TABLE surgical_cases
            ADD COLUMN IF NOT EXISTS assisting_surgeon_id INTEGER REFERENCES surgeons(id)
        """))
        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS ix_surgical_cases_assisting_surgeon
            ON surgical_cases(assisting_surgeon_id)
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS co_surgeon_pairs (
                id SERIAL PRIMARY KEY,
                primary_surgeon_id INTEGER NOT NULL REFERENCES surgeons(id) ON DELETE CASCADE,
                assisting_surgeon_id INTEGER NOT NULL REFERENCES surgeons(id) ON DELETE CASCADE,
                is_active BOOLEAN NOT NULL DEFAULT TRUE,
                note TEXT,
                created_at TIMESTAMP DEFAULT now(),
                UNIQUE (primary_surgeon_id, assisting_surgeon_id)
            )
        """))

        # Seed: Jorge Florin (primary) + Froehling (assisting). Restrict to
        # physicians so staff with the same last name (e.g. Bailey Florin) are
        # never paired. Only insert if the pair (in either direction) is absent.
        conn.execute(text("""
            INSERT INTO co_surgeon_pairs (primary_surgeon_id, assisting_surgeon_id, is_active, note)
            SELECT p.id, a.id, TRUE, 'Seeded: Froehling assists Florin (Advent shared cases)'
            FROM surgeons p, surgeons a
            WHERE p.last_name ILIKE 'florin'
              AND p.first_name ILIKE 'jorge%'
              AND COALESCE(p.staff_type, 'physician') = 'physician'
              AND a.last_name ILIKE 'froehling'
              AND COALESCE(a.staff_type, 'physician') = 'physician'
              AND p.id <> a.id
              AND NOT EXISTS (
                SELECT 1 FROM co_surgeon_pairs c
                WHERE (c.primary_surgeon_id = p.id AND c.assisting_surgeon_id = a.id)
                   OR (c.primary_surgeon_id = a.id AND c.assisting_surgeon_id = p.id)
              )
            LIMIT 1
        """))
        # Clean up any prior over-broad seed that paired staff named Florin.
        conn.execute(text("""
            DELETE FROM co_surgeon_pairs c
            USING surgeons p
            WHERE c.primary_surgeon_id = p.id
              AND p.last_name ILIKE 'florin'
              AND COALESCE(p.staff_type, 'physician') <> 'physician'
        """))
