"""Epic fax room codes: which ones name one real location, which are placeholders.

Don's rule 7: a valid Epic room code that maps to exactly one location is used.
A placeholder code (practice bucket, shared suite) falls back to surgeon + date +
time against that surgeon's existing cards. If sources disagree or nothing is
clear, the row is held and flagged.

Seeded from CAL's resolver code maps and fax line history (Sep-Oct 2026).
`confirmed=False` codes are treated like placeholders until Don confirms them.
Seeding only inserts missing codes, so an admin's later edit is never overwritten.
"""

from __future__ import annotations

from sqlalchemy import text

# (code, location abbreviation or None, kind, confirmed, note)
SEED_ROOM_CODES: tuple[tuple[str, str | None, str, bool, str], ...] = (
    # Placeholders named by Don.
    ("AHMGGENSRG", None, "placeholder", True, "Don: practice-wide bucket"),
    ("AHMGENSRG", None, "placeholder", True, "Don: OCR/short form of AHMGGENSRG"),
    ("MGORLGSDLGIO", None, "placeholder", True, "Don: placeholder"),
    ("MGWDGDS", None, "placeholder", True, "Don: placeholder"),
    ("MGLKMGGENSURG", None, "placeholder", True, "Don: placeholder"),
    ("MGALTGS", None, "placeholder", True, "Don: placeholder"),
    ("WGD S07", None, "placeholder", True, "Don: placeholder"),
    ("WGD S08", None, "placeholder", True, "Don: placeholder"),
    ("ALT S07", None, "placeholder", True, "Don: placeholder"),
    ("APK S02", None, "placeholder", True, "Don: placeholder"),
    ("APK S03", None, "placeholder", True, "Don: placeholder"),
    ("MIN S05", None, "placeholder", True, "Don: placeholder"),
    # Placeholders inferred from history (variants / multi-location). Need Don's OK.
    ("AHMGCENSRG", None, "placeholder", False, "OCR variant of AHMGGENSRG"),
    ("AHMQGENSRG", None, "placeholder", False, "OCR variant of AHMGGENSRG"),
    ("MGLKMGENSURG", None, "placeholder", False, "Spelling seen on faxes; Don listed MGLKMGGENSURG; history LM-OV/AP-OV/AP-OR/AL-OR"),
    ("MGWGDGS", None, "placeholder", False, "Likely same as Don's MGWDGDS; history WG-OV/AL-OR/WG-OR"),
    ("MCWGDGS", None, "placeholder", False, "OCR variant of MGWGDGS"),
    ("CLMMFLGS", None, "placeholder", False, "History CL-OV (1768) and AL-OR (39)"),
    # Real rooms: one location in all history.
    ("ALT OS01", "AL-OR", "room", True, "history AL-OR only"),
    ("ALT OS02", "AL-OR", "room", True, "history AL-OR only"),
    ("ALT S01", "AL-OR", "room", True, "history AL-OR only"),
    ("ALT S04", "AL-OR", "room", True, "history AL-OR only"),
    ("ALTGI", "AL-OR", "room", True, "history AL-OR only"),
    ("MIN S04", "MN-OR", "room", True, "history MN-OR only"),
    ("MIN ENDO", "MN-OR", "room", True, "history MN-OR only"),
    ("WGDOSOR", "WG-OR", "room", True, "history WG-OR only"),
    # Probably real, but thin or mixed history. Need Don's OK.
    ("ALT S09", "AL-OR", "room", False, "no applied history; ALT prefix"),
    ("APK S01", "AP-OR", "room", False, "1 applied line went to AL-OV"),
    ("APK S04", "AP-OR", "room", False, "history AP-OR 7, CL-OV 2, AL-OR 1"),
    ("WGD S09", "WG-OR", "room", False, "2 applied lines went to WG-OV"),
    ("WGDS BEDSIDE", None, "room", False, "1 applied line went to AL-OV; location unknown"),
)


def seed_fax_room_codes(conn) -> int:
    """Insert missing seed codes. Never updates an existing code."""
    added = 0
    for code, abbr, kind, confirmed, note in SEED_ROOM_CODES:
        exists = conn.execute(text("SELECT 1 FROM fax_room_codes WHERE code = :code"), {"code": code}).first()
        if exists:
            continue
        location_id = None
        if abbr:
            location_id = conn.execute(
                text("SELECT id FROM locations WHERE abbreviation = :abbr ORDER BY id LIMIT 1"),
                {"abbr": abbr},
            ).scalar()
        conn.execute(
            text("""
                INSERT INTO fax_room_codes (code, location_id, kind, confirmed, note)
                VALUES (:code, :location_id, :kind, :confirmed, :note)
            """),
            {"code": code, "location_id": location_id, "kind": kind, "confirmed": confirmed, "note": note},
        )
        added += 1
    return added
