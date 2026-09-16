"""Pure clinic weekly grid (site × day × AM/PM) — MFSA master clinic template.

Separate from Block OR. CBO / Surgery One is not on this grid.
Gray cells = no clinic that session. Initials = surgeon clinic day.
"""
from __future__ import annotations

# Site label on paper → CAL location abbreviation (clinic OV only)
SITE_TO_ABBREV = {
    "WG": "WG-OV",
    "CLER": "CL-OV",
    "AP": "AP-OV",
    "Lk M": "LM-OV",
    "ALT": "AL-OV",
    "DP": "DP-OV",
}

# Paper grid: site → session → [Mon..Fri] initials or None (gray)
CLINIC_GRID: dict[str, dict[str, list[str | None]]] = {
    "WG": {
        "am": [None, "OK", None, "AS", "OK"],
        "pm": [None, "JF", None, "JF", None],
    },
    "CLER": {
        "am": ["JB", "JB", "CJ", "CJ", "JP"],
        "pm": ["AS", "CJ", "JP", "JB", None],
    },
    "AP": {
        "am": ["LW", None, "OK", None, "LW"],
        "pm": ["JF", None, "AS", None, None],
    },
    "Lk M": {
        "am": ["LN", None, "GY", None, None],
        "pm": ["NF", None, None, None, None],
    },
    "ALT": {
        "am": [None, "LW", None, "NF", "JD"],
        "pm": [None, "GY", None, "LN", None],
    },
    "DP": {
        "am": [None, None, None, None, None],
        "pm": ["OK", None, None, None, None],
    },
}


def clinic_cells_by_surgeon() -> dict[str, dict[tuple[int, str], str]]:
    """initials → {(dow, session): location_abbrev} for pure clinic days."""
    out: dict[str, dict[tuple[int, str], str]] = {}
    for site, sessions in CLINIC_GRID.items():
        abbrev = SITE_TO_ABBREV[site]
        for session, days in sessions.items():
            for dow, initials in enumerate(days):
                if not initials:
                    continue
                key = initials.strip().upper()
                out.setdefault(key, {})[(dow, session)] = abbrev
    return out
