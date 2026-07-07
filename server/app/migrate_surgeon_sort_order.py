from sqlalchemy import text

from .database import engine


def run_migration():
    if engine.dialect.name == "sqlite":
        return
    with engine.begin() as conn:
        conn.execute(text("""
            ALTER TABLE surgeons
            ADD COLUMN IF NOT EXISTS sort_order INTEGER NOT NULL DEFAULT 0
        """))

        conn.execute(text("""
            WITH ranked AS (
                SELECT
                    id,
                    row_number() OVER (
                        ORDER BY lower(coalesce(last_name, '')), lower(coalesce(first_name, '')), id
                    ) * 10 AS new_sort_order
                FROM surgeons
                WHERE coalesce(staff_type, 'physician') = 'physician'
                  AND coalesce(sort_order, 0) = 0
            )
            UPDATE surgeons AS s
            SET sort_order = ranked.new_sort_order
            FROM ranked
            WHERE s.id = ranked.id
        """))
