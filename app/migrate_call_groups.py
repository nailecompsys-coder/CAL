"""
One-time migration: add call_group_id to call_rotations and make surgeon_id nullable.
Seed default hospital call groups and migrate existing primary/backup rotations into them.
New tables (call_groups, call_group_locations) are created by Base.metadata.create_all.
Run automatically on app startup (idempotent).
"""
from sqlalchemy import text

from .database import engine

GROUP1_NAME = "Winter Garden / Apopka / Minneola Hospital"
GROUP2_NAME = "Altamonte Hospital"


def run():
    with engine.begin() as conn:
        # Add call_group_id if missing (existing DBs)
        conn.execute(text("""
            ALTER TABLE call_rotations
            ADD COLUMN IF NOT EXISTS call_group_id INTEGER REFERENCES call_groups(id)
        """))
        # Allow NULL surgeon_id for "NO call"
        conn.execute(text("""
            ALTER TABLE call_rotations
            ALTER COLUMN surgeon_id DROP NOT NULL
        """))


def seed_default_call_groups():
    """Create default hospital call groups if missing; migrate primary→group1, backup→group2."""
    with engine.begin() as conn:
        # Create group 1 if not exists
        conn.execute(text("""
            INSERT INTO call_groups (name, sort_order)
            SELECT :name, 0
            WHERE NOT EXISTS (SELECT 1 FROM call_groups WHERE name = :name)
        """), {"name": GROUP1_NAME})
        # Create group 2 if not exists
        conn.execute(text("""
            INSERT INTO call_groups (name, sort_order)
            SELECT :name, 1
            WHERE NOT EXISTS (SELECT 1 FROM call_groups WHERE name = :name)
        """), {"name": GROUP2_NAME})
        # Migrate: primary rotations with no group → group 1
        conn.execute(text("""
            UPDATE call_rotations
            SET call_group_id = (SELECT id FROM call_groups WHERE name = :name LIMIT 1)
            WHERE call_group_id IS NULL AND rotation_type = 'primary'
        """), {"name": GROUP1_NAME})
        # Migrate: backup rotations with no group → group 2
        conn.execute(text("""
            UPDATE call_rotations
            SET call_group_id = (SELECT id FROM call_groups WHERE name = :name LIMIT 1)
            WHERE call_group_id IS NULL AND rotation_type = 'backup'
        """), {"name": GROUP2_NAME})
        merge_duplicate_call_groups(conn)
        reclaim_orphan_call_rotations(conn)


def reclaim_orphan_call_rotations(conn):
    """Assign any rotations still with call_group_id NULL to the correct group (primary→group1, backup→group2). Runs every startup so restored backups or late-inserted rows get fixed."""
    conn.execute(text("""
        UPDATE call_rotations
        SET call_group_id = (SELECT id FROM call_groups WHERE name = :name LIMIT 1)
        WHERE call_group_id IS NULL AND rotation_type = 'primary'
    """), {"name": GROUP1_NAME})
    conn.execute(text("""
        UPDATE call_rotations
        SET call_group_id = (SELECT id FROM call_groups WHERE name = :name LIMIT 1)
        WHERE call_group_id IS NULL AND rotation_type = 'backup'
    """), {"name": GROUP2_NAME})


def merge_duplicate_call_groups(conn):
    """Merge duplicate call groups (same name): keep min(id), reassign rotations and locations, delete duplicates."""
    # Find duplicate names: names that appear more than once
    dupes = conn.execute(text("""
        SELECT name, array_agg(id ORDER BY id) AS ids
        FROM call_groups
        GROUP BY name
        HAVING count(*) > 1
    """)).fetchall()
    for (name, ids) in dupes:
        ids_list = list(ids) if hasattr(ids, "__iter__") and not isinstance(ids, str) else [ids]
        if len(ids_list) < 2:
            continue
        keep_id = min(ids_list)
        for gid in ids_list:
            if gid == keep_id:
                continue
            # Reassign rotations from duplicate to kept group
            conn.execute(text("""
                UPDATE call_rotations SET call_group_id = :keep_id WHERE call_group_id = :gid
            """), {"keep_id": keep_id, "gid": gid})
            # Copy location links from duplicate to kept (skip if keep already has that location)
            conn.execute(text("""
                INSERT INTO call_group_locations (call_group_id, location_id)
                SELECT :keep_id, a.location_id FROM call_group_locations a
                WHERE a.call_group_id = :gid
                AND NOT EXISTS (
                    SELECT 1 FROM call_group_locations b
                    WHERE b.call_group_id = :keep_id AND b.location_id = a.location_id
                )
            """), {"keep_id": keep_id, "gid": gid})
            conn.execute(text("DELETE FROM call_group_locations WHERE call_group_id = :gid"), {"gid": gid})
            # Delete duplicate group
            conn.execute(text("DELETE FROM call_groups WHERE id = :gid"), {"gid": gid})


def normalize_surgeon_colors(conn):
    """Staff/physician rows: no per-person calendar color (facilities/hospitals only)."""
    conn.execute(text("UPDATE surgeons SET color = '#ffffff'"))


def run_migration():
    """Idempotent: safe to call every startup."""
    try:
        run()
        seed_default_call_groups()
        # Reclaim again after merge so any NULL rotations (e.g. from backup restore) get assigned
        with engine.begin() as conn:
            reclaim_orphan_call_rotations(conn)
            normalize_surgeon_colors(conn)
    except Exception as e:
        # If call_groups doesn't exist yet, create_all hasn't run; skip and let next startup retry
        if "call_groups" in str(e) or "does not exist" in str(e).lower():
            return
        raise
