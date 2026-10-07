"""Call Builder: access flags, holidays seed, draft table via create_all."""

from sqlalchemy import text

from .database import engine

# Fixed US dates for the six big national holidays (not observed-Monday shifts for NY/July4/Xmas).
_HOLIDAYS = (
    ("2025-01-01", "New Year's"),
    ("2025-05-26", "Memorial Day"),
    ("2025-07-04", "July 4th"),
    ("2025-09-01", "Labor Day"),
    ("2025-11-27", "Thanksgiving"),
    ("2025-12-25", "Christmas"),
    ("2026-01-01", "New Year's"),
    ("2026-05-25", "Memorial Day"),
    ("2026-07-04", "July 4th"),
    ("2026-09-07", "Labor Day"),
    ("2026-11-26", "Thanksgiving"),
    ("2026-12-25", "Christmas"),
    ("2027-01-01", "New Year's"),
    ("2027-05-31", "Memorial Day"),
    ("2027-07-04", "July 4th"),
    ("2027-09-06", "Labor Day"),
    ("2027-11-25", "Thanksgiving"),
    ("2027-12-25", "Christmas"),
)


def run_migration():
    if engine.dialect.name == "sqlite":
        return

    with engine.begin() as conn:
        conn.execute(text("""
            ALTER TABLE admin_users
            ADD COLUMN IF NOT EXISTS can_call_builder BOOLEAN NOT NULL DEFAULT FALSE
        """))
        conn.execute(text("""
            ALTER TABLE surgeons
            ADD COLUMN IF NOT EXISTS can_call_builder BOOLEAN NOT NULL DEFAULT FALSE
        """))
        for day, name in _HOLIDAYS:
            conn.execute(text("""
                INSERT INTO holidays (date, name)
                SELECT CAST(:day AS DATE), :name
                WHERE NOT EXISTS (SELECT 1 FROM holidays WHERE date = CAST(:day AS DATE))
            """), {"day": day, "name": name})
        # Chris and Amy only (portal + phone records).
        conn.execute(text("""
            UPDATE admin_users
            SET can_call_builder = TRUE
            WHERE lower(username) IN ('cjohnson', 'amydiehl13')
               OR (lower(coalesce(first_name, '')) IN ('chris', 'christopher')
                   AND lower(coalesce(last_name, '')) = 'johnson')
               OR (lower(coalesce(first_name, '')) = 'amy'
                   AND lower(coalesce(last_name, '')) = 'diehl')
        """))
        conn.execute(text("""
            UPDATE surgeons
            SET can_call_builder = TRUE
            WHERE (lower(coalesce(first_name, '')) IN ('chris', 'christopher')
                   AND lower(coalesce(last_name, '')) = 'johnson')
               OR (lower(coalesce(first_name, '')) = 'amy'
                   AND lower(coalesce(last_name, '')) = 'diehl')
        """))
