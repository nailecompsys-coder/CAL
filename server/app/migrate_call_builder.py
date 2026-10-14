"""Call Builder: access flags, holidays seed, draft table via create_all."""

from sqlalchemy import text

from .database import engine

# Fixed calendar dates (not observed-Monday shifts for NY/July4/Xmas).
# Credit is only when a surgeon is on call that holiday date.
# Halloween stays for phone/portal calendar emoji only — not a work-holiday credit.
_HOLIDAYS = (
    ("2025-01-01", "New Year's"),
    ("2025-02-17", "Presidents Day"),
    ("2025-04-20", "Easter"),
    ("2025-05-11", "Mother's Day"),
    ("2025-05-26", "Memorial Day"),
    ("2025-06-15", "Father's Day"),
    ("2025-07-04", "July 4th"),
    ("2025-09-01", "Labor Day"),
    ("2025-10-31", "Halloween"),
    ("2025-11-27", "Thanksgiving"),
    ("2025-12-24", "Christmas Eve"),
    ("2025-12-25", "Christmas"),
    ("2025-12-31", "New Year's Eve"),
    ("2026-01-01", "New Year's"),
    ("2026-02-16", "Presidents Day"),
    ("2026-04-05", "Easter"),
    ("2026-05-10", "Mother's Day"),
    ("2026-05-25", "Memorial Day"),
    ("2026-06-21", "Father's Day"),
    ("2026-07-04", "July 4th"),
    ("2026-09-07", "Labor Day"),
    ("2026-10-31", "Halloween"),
    ("2026-11-26", "Thanksgiving"),
    ("2026-12-24", "Christmas Eve"),
    ("2026-12-25", "Christmas"),
    ("2026-12-31", "New Year's Eve"),
    ("2027-01-01", "New Year's"),
    ("2027-02-15", "Presidents Day"),
    ("2027-03-28", "Easter"),
    ("2027-05-09", "Mother's Day"),
    ("2027-05-31", "Memorial Day"),
    ("2027-06-20", "Father's Day"),
    ("2027-07-04", "July 4th"),
    ("2027-09-06", "Labor Day"),
    ("2027-10-31", "Halloween"),
    ("2027-11-25", "Thanksgiving"),
    ("2027-12-24", "Christmas Eve"),
    ("2027-12-25", "Christmas"),
    ("2027-12-31", "New Year's Eve"),
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
