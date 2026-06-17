"""Shared visibility rules for clinician records."""

from __future__ import annotations

from .models import Surgeon

HIDDEN_SURGEON_EMAILS = {"don@clermontitstore.com"}
HIDDEN_SURGEON_NAMES = {("developer", "admin")}


def surgeon_is_hidden(surgeon: Surgeon | None) -> bool:
    if not surgeon:
        return False
    email = (surgeon.email or "").strip().lower()
    first = (surgeon.first_name or "").strip().lower()
    last = (surgeon.last_name or "").strip().lower()
    return email in HIDDEN_SURGEON_EMAILS or (first, last) in HIDDEN_SURGEON_NAMES


def surgeon_is_visible(surgeon: Surgeon | None) -> bool:
    return bool(surgeon and surgeon.is_active and not surgeon_is_hidden(surgeon))


def visible_surgeons(surgeons: list[Surgeon]) -> list[Surgeon]:
    return [surgeon for surgeon in surgeons if not surgeon_is_hidden(surgeon)]
