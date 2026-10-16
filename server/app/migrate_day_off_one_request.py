"""One live day-off request per surgeon and date range. No Call is its own row."""

from sqlalchemy import text

from .database import engine

_LEAVE = "lower(trim(coalesce(reason, ''))) <> 'no call'"
_NO_CALL = "lower(trim(coalesce(reason, ''))) = 'no call'"
_LIVE = "status IN ('pending', 'approved')"


def apply(conn) -> None:
    conn.execute(text("""
        UPDATE days_off
        SET start_date = end_date,
            end_date = start_date
        WHERE start_date > end_date
    """))
    conn.execute(text("""
        DELETE FROM days_off AS extra
        WHERE extra.id IN (
            SELECT ranked.id
            FROM (
                SELECT id,
                       row_number() OVER (
                           PARTITION BY surgeon_id, start_date, end_date,
                               CASE WHEN lower(trim(coalesce(reason, ''))) = 'no call'
                                    THEN 'no_call' ELSE 'leave' END
                           ORDER BY CASE status WHEN 'approved' THEN 0
                                                 WHEN 'pending' THEN 1
                                                 ELSE 2 END,
                                    id
                       ) AS n
                FROM days_off
                WHERE status IN ('pending', 'approved')
            ) AS ranked
            WHERE ranked.n > 1
        )
    """))
    conn.execute(text("""
        DO $$ BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint WHERE conname = 'ck_days_off_start_before_end'
            ) THEN
                ALTER TABLE days_off
                    ADD CONSTRAINT ck_days_off_start_before_end
                    CHECK (start_date <= end_date);
            END IF;
        END $$
    """))
    conn.execute(text(f"""
        CREATE UNIQUE INDEX IF NOT EXISTS uq_days_off_live_leave
        ON days_off (surgeon_id, start_date, end_date)
        WHERE {_LIVE} AND {_LEAVE}
    """))
    conn.execute(text(f"""
        CREATE UNIQUE INDEX IF NOT EXISTS uq_days_off_live_no_call
        ON days_off (surgeon_id, start_date, end_date)
        WHERE {_LIVE} AND {_NO_CALL}
    """))


def run_migration() -> None:
    if engine.dialect.name == "sqlite":
        return
    with engine.begin() as conn:
        apply(conn)
