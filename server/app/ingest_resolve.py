"""Shared name/location resolution for Desk → CAL ingest."""
from __future__ import annotations

import re
from datetime import date

from sqlalchemy.orm import Session, joinedload

from .models import ClinicSchedule, Location, Surgeon

_CRED_RE = re.compile(
    r"\b(?:dr\.?|md|do|pa\s*-?\s*c|pac|np|aprn|facs|phd|mba|rn|lpn)\b",
    re.IGNORECASE,
)


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


def resolve_surgeon(db: Session, raw: str | None) -> Surgeon | None:
    if not raw or not str(raw).strip():
        return None
    parts = _name_parts(str(raw))
    if not parts:
        return None
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

        if len(parts) >= 2 and first and last:
            if _first_close(parts[0], first) and parts[-1] == last:
                scored.append((90, s))
                continue
            if parts[-1] == last and any(_first_close(p, first) for p in parts[:-1]):
                scored.append((85, s))
                continue

        if last and parts[-1] == last:
            scored.append((50, s))
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
    return abbr.endswith("-CL") or ltype == "clinic"


def _loc_by_abbr(db: Session, abbr: str) -> Location | None:
    return db.query(Location).filter(Location.abbreviation == abbr).first()


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
    aliases = (
        ("APK", "AP-OR"),
        ("APOPKA OR", "AP-OR"),
        ("APOPKA CLINIC", "AP-CL"),
        ("WGD", "WG-OR"),
        ("WINTER GARDEN OR", "WG-OR"),
        ("WINTER GARDEN CLINIC", "WG-CL"),
        ("MIN", "MN-OR"),
        ("MINNEOLA OR", "MN-OR"),
        ("HEALTH PARK", "HP-CL"),
        ("HP-CL", "HP-CL"),
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
    like AHMGGENSRG are not reliable facility labels (HP is clinic-only; Florin
    7/27 clinic is AP-CL, not HP-CL).
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
    code_map = (
        ("MGALTGS", "AL-CL"),
        ("MGLKM", "LM-CL"),
        ("AHWG", "WG-CL"),
        ("WINTERGARDEN", "WG-CL"),
        ("APOPKA", "AP-CL"),
        ("MINNEOLA", "MN-CL"),
        ("LAKEMARY", "LM-CL"),
        ("ALTAMONTE", "AL-CL"),
        ("HEALTHPARK", "HP-CL"),
        # Advent generic group codes — only when no schedule override above
        ("AHMGGEN", "HP-CL"),
        ("CLMMFLGS", "HP-CL"),
        ("CLMM", "HP-CL"),
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
