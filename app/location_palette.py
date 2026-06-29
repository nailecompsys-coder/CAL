from __future__ import annotations

from typing import Optional

from sqlalchemy.orm import Session

from .models import Location


LOCATION_PALETTE = {
    "altamonte office": "#D8F6F0",
    "altamonte or": "#79CDBD",
    "apopka office": "#DDF2FC",
    "apopka or": "#7CBFDE",
    "clermont office": "#FCF0D4",
    "lake mary office": "#F0E3FC",
    "minneola office": "#FDE9DD",
    "minneola or": "#E8A17C",
    "winter garden office": "#FCE2E8",
    "winter garden or": "#E48EA6",
    "float": "#D9E4EA",
}


SITE_FAMILIES = {
    "altamonte": {"clinic": "#D8F6F0", "hospital": "#79CDBD"},
    "apopka": {"clinic": "#DDF2FC", "hospital": "#7CBFDE"},
    "minneola": {"clinic": "#FDE9DD", "hospital": "#E8A17C"},
    "winter garden": {"clinic": "#FCE2E8", "hospital": "#E48EA6"},
}


def normalize_location_name(name: str) -> str:
    return " ".join((name or "").strip().lower().split())


def resolve_palette_color(name: str, location_type: str) -> Optional[str]:
    normalized_name = normalize_location_name(name)
    if not normalized_name:
        return None

    exact = LOCATION_PALETTE.get(normalized_name)
    if exact:
        return exact

    if normalized_name == "float":
        return LOCATION_PALETTE["float"]

    for suffix in (" office", " clinic", " or"):
        if normalized_name.endswith(suffix):
            site_key = normalized_name[: -len(suffix)].strip()
            family = SITE_FAMILIES.get(site_key)
            if family:
                return family.get(location_type)

    family = SITE_FAMILIES.get(normalized_name)
    if family:
        return family.get(location_type)

    return None


def ensure_location_palette_seeded(db: Session) -> int:
    """Legacy no-op: location colors are now admin-managed."""
    return 0
