"""Epic fax room codes: real rooms vs Epic placeholders, decided by pattern.

Don's room rule: a real room is a 3-letter site code followed by a room
(MIN S05, WGD S08, ALT S07, APK S02, ALT OS01). The site code names the
location. Anything else (MGALTGS, AHMGGENSRG, ALTGI, MIN ENDO, ...) is an Epic
placeholder: it never causes a location conflict and the row is placed by
surgeon + date + time against that surgeon's existing card.

A code that looks like a room but has an unknown site is stored as an
unconfirmed room with no location, so it neither places nor contradicts a row.
"""

from __future__ import annotations

import re

from sqlalchemy import text

# Epic site code -> CAL OR location abbreviation.
SITE_LOCATIONS: dict[str, str] = {
    "ALT": "AL-OR",
    "APK": "AP-OR",
    "MIN": "MN-OR",
    "WGD": "WG-OR",
}

ROOM_PATTERN = re.compile(r"^([A-Z]{3}) ?O?S?\d+$")

# Codes seen on faxes (Sep-Oct 2026); classification comes from the pattern.
SEEN_CODES: tuple[str, ...] = (
    "AHMGGENSRG", "AHMGENSRG", "AHMGCENSRG", "AHMQGENSRG", "MGORLGSDLGIO", "MGWDGDS",
    "MGWGDGS", "MCWGDGS", "MGLKMGGENSURG", "MGLKMGENSURG", "MGALTGS", "CLMMFLGS",
    "ALTGI", "MIN ENDO", "WGDOSOR", "WGDS BEDSIDE",
    "ALT OS01", "ALT OS02", "ALT S01", "ALT S04", "ALT S07", "ALT S09",
    "APK S01", "APK S02", "APK S03", "APK S04",
    "MIN S04", "MIN S05", "WGD S07", "WGD S08", "WGD S09",
)


def normalize_room_code(raw: str | None) -> str:
    return (raw or "").strip().upper()


def classify_room_code(raw: str | None) -> tuple[str, str | None]:
    """Return (kind, site location abbreviation or None)."""
    code = normalize_room_code(raw)
    match = ROOM_PATTERN.match(code)
    if not match:
        return "placeholder", None
    return "room", SITE_LOCATIONS.get(match.group(1))


def _location_id(conn, abbr: str | None):
    if not abbr:
        return None
    return conn.execute(
        text("SELECT id FROM locations WHERE abbreviation = :abbr ORDER BY id LIMIT 1"), {"abbr": abbr}
    ).scalar()


def register_room_codes(conn, codes, *, resync: bool = False) -> int:
    """Insert missing codes classified by pattern; resync rewrites existing ones."""
    changed = 0
    for code in sorted({normalize_room_code(c) for c in codes if normalize_room_code(c)}):
        kind, abbr = classify_room_code(code)
        location_id = _location_id(conn, abbr)
        confirmed = kind == "placeholder" or location_id is not None
        note = f"pattern: site {code[:3]} -> {abbr}" if abbr else (
            "pattern: room shape, unknown site" if kind == "room" else "pattern: Epic placeholder")
        params = {"code": code, "location_id": location_id, "kind": kind, "confirmed": confirmed, "note": note}
        exists = conn.execute(text("SELECT 1 FROM fax_room_codes WHERE code = :code"), {"code": code}).first()
        if exists and not resync:
            continue
        if exists:
            conn.execute(text("""UPDATE fax_room_codes SET location_id = :location_id, kind = :kind,
                                 confirmed = :confirmed, note = :note WHERE code = :code"""), params)
        else:
            conn.execute(text("""INSERT INTO fax_room_codes (code, location_id, kind, confirmed, note)
                                 VALUES (:code, :location_id, :kind, :confirmed, :note)"""), params)
        changed += 1
    return changed


def seed_fax_room_codes(conn) -> int:
    """Seed known codes and reclassify every stored code by Don's pattern rule."""
    stored = [row[0] for row in conn.execute(text("SELECT code FROM fax_room_codes"))]
    return register_room_codes(conn, list(SEEN_CODES) + stored, resync=True)
