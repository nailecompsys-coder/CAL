"""Idempotent location admin schema updates."""

from sqlalchemy import text

from .database import SessionLocal, engine
from .models import Location
from .api_calendar_utils import location_abbrev


def run_migration():
    with engine.begin() as conn:
        conn.execute(text("""
            ALTER TABLE locations
            ADD COLUMN IF NOT EXISTS abbreviation VARCHAR(12)
        """))

    db = SessionLocal()
    try:
        updated = 0
        for loc in db.query(Location).all():
            current = (loc.abbreviation or "").strip()
            if not current:
                loc.abbreviation = location_abbrev(loc)[:12] or "LOC"
                updated += 1
        if updated:
            db.commit()
    finally:
        db.close()

    with engine.begin() as conn:
        conn.execute(text("""
            ALTER TABLE locations
            ALTER COLUMN abbreviation SET DEFAULT 'LOC'
        """))
        conn.execute(text("""
            UPDATE locations
            SET abbreviation = 'LOC'
            WHERE abbreviation IS NULL OR trim(abbreviation) = ''
        """))
        conn.execute(text("""
            ALTER TABLE locations
            ALTER COLUMN abbreviation SET NOT NULL
        """))
