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
    """Return (kind, 3-letter Epic site code or None)."""
    code = normalize_room_code(raw)
    match = ROOM_PATTERN.match(code)
    if not match:
        return "placeholder", None
    return "room", match.group(1)


def _is_subsequence(short: str, long: str) -> bool:
    it = iter(long)
    return all(ch in it for ch in short)


def site_location_map(conn) -> dict[str, tuple[int, str]]:
    """Map Epic site codes to OR locations from CAL's `locations` table (source of truth).

    An OR location's site letters are its abbreviation before the dash (AL-OR -> AL).
    An Epic site code matches when it starts with the same letter and contains those
    letters in order (ALT -> AL, APK -> AP, WGD -> WG, MIN -> MN). Only active
    hospital locations are rooms; a site matching zero or several stays unmapped.
    """
    rows = conn.execute(text(
        "SELECT id, abbreviation FROM locations WHERE location_type = 'hospital' AND is_active = :on "
        "AND abbreviation IS NOT NULL"), {"on": True}).all()
    return {"_rows": rows}  # resolved lazily per site by site_location()


def site_location(conn, site: str | None, _cache: dict | None = None) -> tuple[int, str] | None:
    if not site:
        return None
    rows = (_cache or site_location_map(conn))["_rows"]
    hits = [(lid, abbr) for lid, abbr in rows
            if (letters := abbr.split("-")[0].upper()) and letters[0] == site[0] and _is_subsequence(letters, site)]
    return hits[0] if len(hits) == 1 else None


def register_room_codes(conn, codes, *, resync: bool = False) -> int:
    """Insert missing codes classified by pattern; resync rewrites existing ones."""
    changed = 0
    cache = site_location_map(conn)
    for code in sorted({normalize_room_code(c) for c in codes if normalize_room_code(c)}):
        kind, site = classify_room_code(code)
        hit = site_location(conn, site, cache)
        location_id, abbr = hit if hit else (None, None)
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
