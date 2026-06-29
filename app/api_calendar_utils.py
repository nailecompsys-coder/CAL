"""Shared calendar API event formatting helpers."""

import re

NEUTRAL_CAL_BG = "#F4F6F9"
NEUTRAL_CAL_TEXT = "#4A6080"

SORT_DAYOFF, SORT_NOCALL, SORT_CALL, SORT_CLINIC, SORT_MTG, SORT_SURG = 0, 1, 2, 3, 4, 5


def pastel_from_location_hex(loc_hex: str) -> str:
    h = (loc_hex or "").strip()
    if len(h) == 7 and h.startswith("#"):
        return h + "99"
    return "#7dd3fc99"


def call_group_abbrev(name):
    """Short label for call group (e.g. 'Winter Garden / Apopka' -> 'WG')."""
    if not name:
        return "?"
    s = re.sub(r"\s*(/|-)\s*", " ", name).strip()
    words = [w for w in s.split() if len(w) >= 2 and w.lower() not in ("hospital", "and", "the")]
    if not words:
        return (s[:3] or "?").upper()
    if len(words) == 1:
        return words[0][:2].upper()
    return "".join(w[0] for w in words[:3]).upper()


def location_abbrev(loc, location_type=None):
    """Admin-defined location abbreviation, with generated fallback for legacy rows."""
    if not loc or not getattr(loc, "name", None):
        return "AH" if location_type == "hospital" else "CL"
    custom = (getattr(loc, "abbreviation", None) or "").strip()
    if custom:
        return custom.upper()[:12]
    name = (loc.name or "").strip()
    t = (location_type or getattr(loc, "location_type", None) or "clinic").lower()
    prefix = "AH" if t == "hospital" else "CL"
    name = re.sub(r"\s*(advent\s*health|hospital|clinic)\s*", " ", name, flags=re.I).strip()
    words = name.split()
    if not words:
        return prefix
    first = words[0][:4] if words[0] else ""
    return f"{prefix}-{first}" if first else prefix


def surgeon_initials(surgeon) -> str:
    try:
        return surgeon.initials
    except Exception:
        return ((surgeon.first_name or "?")[0] + (surgeon.last_name or "?")[0]).upper()
