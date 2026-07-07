"""Idempotent location admin schema updates."""

from sqlalchemy import text

from .database import SessionLocal, engine
from .models import Location
from .api_calendar_utils import location_abbrev


def normalize_office_location_name(name: str | None) -> str:
    if not name:
        return name or ""
    words = []
    changed = False
    for word in name.split(" "):
        if word.lower() == "office":
            words.append("Clinic")
            changed = True
        else:
            words.append(word)
    return " ".join(words) if changed else name


def run_migration():
    if engine.dialect.name != "sqlite":
        with engine.begin() as conn:
            conn.execute(text("""
                ALTER TABLE locations
                ADD COLUMN IF NOT EXISTS abbreviation VARCHAR(12)
            """))

    db = SessionLocal()
    try:
        updated = 0
        for loc in db.query(Location).all():
            normalized_name = normalize_office_location_name(loc.name)
            if normalized_name != loc.name:
                loc.name = normalized_name
                if (loc.location_type or "clinic") == "clinic":
                    loc.location_type = "clinic"
                updated += 1
            current = (loc.abbreviation or "").strip()
            if not current:
                loc.abbreviation = location_abbrev(loc)[:12] or "LOC"
                updated += 1
        if updated:
            db.commit()
    finally:
        db.close()

    if engine.dialect.name != "sqlite":
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
