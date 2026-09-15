"""Shared name/location resolution for Desk → CAL ingest."""
from __future__ import annotations

import re
from datetime import date

from sqlalchemy.orm import Session, joinedload

from .models import ClinicSchedule, Location, Surgeon, SurgeonOcrAlias

_CRED_RE = re.compile(
    r"\b(?:dr\.?|md|do|pa\s*-?\s*c|pac|np|aprn|facs|phd|mba|rn|lpn)\b",
    re.IGNORECASE,
)

# Common Advent fax OCR misspellings → CAL last-name tokens.
# Prefer fuzzy roster match for new typos; keep known Woodley OCR forms here.
_SURGEON_TOKEN_ALIASES = {
    "wocdley": "woodley",
    "woedley": "woodley",
    "woedly": "woodley",
    "woodely": "woodley",
    "woodtey": "woodley",
    "woodly": "woodley",
}


def _tokens(value: str) -> list[str]:
    s = _CRED_RE.sub(" ", str(value or "").lower())
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return [t for t in s.split() if len(t) > 1]


def _first_close(a: str, b: str) -> bool:
    if not a or not b:
        return False
    if a == b:
        return True
    short, long = (a, b) if len(a) <= len(b) else (b, a)
    return len(short) >= 3 and long.startswith(short)


def _edit_distance(a: str, b: str) -> int:
    """Levenshtein distance for short OCR tokens."""
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    if abs(len(a) - len(b)) > 3:
        return 99
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, start=1):
        cur = [i]
        for j, cb in enumerate(b, start=1):
            ins = cur[j - 1] + 1
            delete = prev[j] + 1
            sub = prev[j - 1] + (0 if ca == cb else 1)
            cur.append(min(ins, delete, sub))
        prev = cur
    return prev[-1]


def _last_close(ocr: str, known: str) -> bool:
    """True when OCR last name matches a known roster last name (small OCR drift).

    Roster is the source of truth — we do not invent new surgeons from OCR.
    """
    if not ocr or not known:
        return False
    if ocr == known:
        return True
    # Same initial keeps Johnson / Nelson-style collisions down.
    if ocr[0] != known[0]:
        return False
    dist = _edit_distance(ocr, known)
    n = max(len(ocr), len(known))
    if n <= 6:
        return dist <= 1
    return dist <= 2


def _name_parts(raw: str) -> list[str]:
    s = str(raw or "").strip()
    if "," in s:
        left, right = [x.strip() for x in s.split(",", 1)]
        left_t = _tokens(left)
        right_t = _tokens(right)
        if not right_t:
            return left_t
        if len(left_t) == 1 and right_t:
            return right_t + left_t
        return left_t + right_t
    return _tokens(s)


def ocr_last_token(raw: str | None) -> str | None:
    """Normalized last-name token from an OCR surgeon string (before alias map)."""
    parts = _name_parts(str(raw or ""))
    return parts[-1] if parts else None


def _db_alias_surgeon(db: Session, token: str) -> Surgeon | None:
    if not token:
        return None
    row = (
        db.query(SurgeonOcrAlias)
        .filter(SurgeonOcrAlias.token == token)
        .first()
    )
    if not row:
        return None
    surgeon = db.get(Surgeon, row.surgeon_id)
    if surgeon and surgeon.is_active:
        return surgeon
    return None


def save_surgeon_ocr_alias(db: Session, raw_ocr_name: str, surgeon_id: int) -> str | None:
    """Persist OCR last token → roster surgeon so the next fax resolves.

    Returns the saved token, or None if nothing to store.
    """
    token = ocr_last_token(raw_ocr_name)
    if not token:
        return None
    surgeon = db.get(Surgeon, surgeon_id)
    if not surgeon or not surgeon.is_active:
        raise ValueError("Surgeon not found")
    tokens = {token, _SURGEON_TOKEN_ALIASES.get(token, token)}
    for t in tokens:
        existing = (
            db.query(SurgeonOcrAlias)
            .filter(SurgeonOcrAlias.token == t)
            .first()
        )
        if existing:
            existing.surgeon_id = surgeon_id
        else:
            db.add(SurgeonOcrAlias(token=t, surgeon_id=surgeon_id))
    db.commit()
    return token


def resolve_surgeon(db: Session, raw: str | None) -> Surgeon | None:
    """Map fax OCR surgeon text to an active roster surgeon.

    Never creates surgeons. Unknown OCR either fuzzy-matches the roster or fails
    so admins can map the OCR token to an existing doctor.
    """
    if not raw or not str(raw).strip():
        return None
    raw_parts = _name_parts(str(raw))
    if not raw_parts:
        return None

    # Explicit admin-saved OCR → surgeon wins immediately.
    db_hit = _db_alias_surgeon(db, raw_parts[-1])
    if db_hit:
        return db_hit

    parts = [_SURGEON_TOKEN_ALIASES.get(p, p) for p in raw_parts]
    needle = " ".join(parts)
    surgeons = db.query(Surgeon).filter(Surgeon.is_active.is_(True)).all()

    scored: list[tuple[int, Surgeon]] = []
    for s in surgeons:
        full = _tokens(s.full_name)
        first_t = _tokens(s.first_name)
        last_t = _tokens(s.last_name)
        first = first_t[0] if first_t else ""
        last = last_t[-1] if last_t else ""
        full_s = " ".join(full)

        if full_s == needle:
            scored.append((100, s))
            continue

        last_ocr = parts[-1]
        last_exact = bool(last and last_ocr == last)
        last_fuzzy = bool(last and not last_exact and _last_close(last_ocr, last))

        if len(parts) >= 2 and first and last:
            if _first_close(parts[0], first) and last_exact:
                scored.append((90, s))
                continue
            if _first_close(parts[0], first) and last_fuzzy:
                scored.append((88, s))
                continue
            if last_exact and any(_first_close(p, first) for p in parts[:-1]):
                scored.append((85, s))
                continue
            if last_fuzzy and any(_first_close(p, first) for p in parts[:-1]):
                scored.append((83, s))
                continue

        if last_exact:
            scored.append((50, s))
            continue
        if last_fuzzy:
            scored.append((48, s))
            continue

        if needle in full_s or (last and last in parts):
            scored.append((40, s))

    if not scored:
        return None
    scored.sort(key=lambda x: x[0], reverse=True)
    best = scored[0][0]
    tops = [s for score, s in scored if score == best]
    if len(tops) > 1 and best < 85:
        return None
    if len(tops) == 1:
        return tops[0]
    return None


def _is_or_location(loc: Location | None) -> bool:
    if not loc:
        return False
    abbr = (loc.abbreviation or "").upper()
    ltype = (loc.location_type or "").lower()
    return abbr.endswith("-OR") or ltype in ("hospital", "or")


def _is_clinic_location(loc: Location | None) -> bool:
    if not loc:
        return False
    abbr = (loc.abbreviation or "").upper()
    ltype = (loc.location_type or "").lower()
    # Prod clinic rows use *-OV (office/visit); older seeds used *-CL.
    return (
        abbr.endswith("-CL")
        or abbr.endswith("-OV")
        or (ltype == "clinic" and not abbr.endswith("-OR"))
    )


def _loc_by_abbr(db: Session, abbr: str) -> Location | None:
    """Find by abbreviation; accept legacy *-CL ↔ live *-OV clinic swap."""
    target = str(abbr or "").strip().upper()
    if not target:
        return None
    loc = db.query(Location).filter(Location.abbreviation == target).first()
    if loc:
        return loc
    if target.endswith("-OV"):
        return (
            db.query(Location)
            .filter(Location.abbreviation == f"{target[:-3]}-CL")
            .first()
        )
    if target.endswith("-CL"):
        return (
            db.query(Location)
            .filter(Location.abbreviation == f"{target[:-3]}-OV")
            .first()
        )
    return None


def schedule_location_for_day(
    db: Session,
    surgeon_id: int,
    day: date,
    *,
    want: str,
    session: str | None = None,
) -> Location | None:
    """Prefer the surgeon's Clinic/OR grid for that date (SSOT for facility).

    want: \"or\" | \"clinic\"
    """
    rows = (
        db.query(ClinicSchedule)
        .options(joinedload(ClinicSchedule.location))
        .filter(
            ClinicSchedule.surgeon_id == surgeon_id,
            ClinicSchedule.date == day,
            ClinicSchedule.assignment_type == "assigned",
            ClinicSchedule.location_id.isnot(None),
        )
        .all()
    )
    if not rows:
        return None

    sess = (session or "").lower() or None

    def _session_ok(row: ClinicSchedule) -> bool:
        rs = (row.session or "full").lower()
        if not sess or sess == "full" or rs == "full":
            return True
        return rs == sess

    preferred = [r for r in rows if _session_ok(r)]
    pool = preferred or rows

    if want == "or":
        for row in pool:
            if _is_or_location(row.location):
                return row.location
        return None

    for row in pool:
        if _is_clinic_location(row.location):
            return row.location
    # A surgeon in the OR this session is still at the clinic named on the other
    # half of the day, so fall back across sessions for the facility name only.
    for row in rows:
        if _is_clinic_location(row.location):
            return row.location
    return None


def resolve_location(db: Session, room_or_site: str | None) -> Location | None:
    """Legacy fuzzy match — avoid loose tokens like PARK (Health Park ≠ Apopka OR)."""
    if not room_or_site or not str(room_or_site).strip():
        return None
    raw = str(room_or_site).strip().upper()
    locs = db.query(Location).all()
    for loc in locs:
        abbr = (loc.abbreviation or "").upper()
        name = (loc.name or "").upper()
        if abbr and (abbr == raw or raw.startswith(abbr + " ") or abbr in raw.split()):
            return loc
        if name and name == raw:
            return loc
    # Explicit Advent room/site aliases only — no substring "PARK"
    # Clinic abbreviations match live CAL rows (*-OV). OR rows stay *-OR.
    aliases = (
        ("APK", "AP-OR"),
        ("APOPKA OR", "AP-OR"),
        ("APOPKA CLINIC", "AP-OV"),
        ("WGD", "WG-OR"),
        ("WINTER GARDEN OR", "WG-OR"),
        ("WINTER GARDEN CLINIC", "WG-OV"),
        ("MIN", "MN-OR"),
        ("MINNEOLA OR", "MN-OR"),
        ("HEALTH PARK", "HP-OV"),
        ("HP-CL", "HP-OV"),
        ("HP-OV", "HP-OV"),
        ("CLERMONT", "CL-OV"),
        ("CL-OV", "CL-OV"),
    )
    for needle, abbr in aliases:
        if needle in raw or raw.startswith(needle):
            loc = _loc_by_abbr(db, abbr)
            if loc:
                return loc
    return None


def resolve_or_location(
    db: Session,
    room_or_site: str | None,
    *,
    surgeon_id: int | None = None,
    day: date | None = None,
    session: str | None = None,
) -> Location | None:
    """Map Advent OR room codes to CAL hospital locations. Never returns a clinic."""
    raw = str(room_or_site or "").strip().upper()
    compact = raw.replace(" ", "")
    prefix_map = (
        ("APK", "AP-OR"),
        ("APOP", "AP-OR"),
        ("WGD", "WG-OR"),
        ("WGDOSOR", "WG-OR"),
        ("MIN", "MN-OR"),
        ("ALT", "AL-OR"),
    )
    if compact:
        for needle, abbr in prefix_map:
            if needle in compact:
                loc = _loc_by_abbr(db, abbr)
                if loc and _is_or_location(loc):
                    return loc

    if surgeon_id and day:
        scheduled = schedule_location_for_day(
            db, surgeon_id, day, want="or", session=session or "am"
        )
        if scheduled:
            return scheduled

    if raw:
        loc = resolve_location(db, room_or_site)
        if loc and _is_or_location(loc):
            return loc
    return None


def resolve_clinic_location(
    db: Session,
    site_raw: str | None,
    *,
    surgeon_id: int | None = None,
    day: date | None = None,
    session: str | None = None,
) -> Location | None:
    """Map Advent clinic site codes to CAL clinic locations.

    Prefer the surgeon's clinic grid for that date when present — fax site codes
    like AHMGGENSRG are not always reliable facility labels.
    """
    if surgeon_id and day:
        scheduled = schedule_location_for_day(
            db, surgeon_id, day, want="clinic", session=session or "pm"
        )
        if scheduled:
            return scheduled

    raw = str(site_raw or "").strip().upper()
    if not raw:
        return None
    compact = raw.replace(" ", "")
    if compact in {"MIN", "MN"}:
        loc = _loc_by_abbr(db, "MN-OV")
        if loc and _is_clinic_location(loc):
            return loc
    # Map Advent fax site codes → live CAL clinic abbreviations (*-OV).
    code_map = (
        ("MGALTGS", "AL-OV"),
        ("MGLKM", "LM-OV"),
        ("AHWG", "WG-OV"),
        ("WINTERGARDEN", "WG-OV"),
        ("WGD", "WG-OV"),
        ("APOPKA", "AP-OV"),
        ("APK", "AP-OV"),
        ("MINNEOLA", "MN-OV"),
        ("MN-OV", "MN-OV"),
        ("LAKEMARY", "LM-OV"),
        ("ALTAMONTE", "AL-OV"),
        ("CLERMONT", "CL-OV"),
        ("CLMMFLGS", "CL-OV"),
        ("CLMM", "CL-OV"),
        ("HEALTHPARK", "HP-OV"),
        # AHMGGENSRG is the practice-wide "AdventHealth Medical Group General
        # Surgery" code, not a facility — only the grid can place that day.
        ("DRPHILLIPS", "DP-OV"),
        ("DP-OV", "DP-OV"),
        # Legacy aliases still accepted if present in a DB
        ("HP-CL", "HP-OV"),
        ("AP-CL", "AP-OV"),
        ("WG-CL", "WG-OV"),
        ("MN-CL", "MN-OV"),
        ("LM-CL", "LM-OV"),
        ("AL-CL", "AL-OV"),
    )
    for needle, abbr in code_map:
        if needle in compact:
            loc = _loc_by_abbr(db, abbr)
            if loc and _is_clinic_location(loc):
                return loc
    loc = resolve_location(db, site_raw)
    if loc and _is_clinic_location(loc):
        return loc
    return None
