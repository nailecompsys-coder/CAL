"""Native surgeon sorting and audience helpers."""

from .models import Surgeon


def native_surgeon_rank_key(surgeon: Surgeon | None) -> tuple:
    if not surgeon:
        return (2, 999999, "", "")
    is_physician = (surgeon.staff_type or "physician") == "physician"
    rank = surgeon.sort_order or 0
    return (
        0 if is_physician else 1,
        rank if is_physician and rank > 0 else 999999,
        (surgeon.last_name or "").lower(),
        (surgeon.first_name or "").lower(),
    )


def native_viewer_sees_physicians(viewer: Surgeon) -> bool:
    return (viewer.staff_type or "").lower() == "physician"
