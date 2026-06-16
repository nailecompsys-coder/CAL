from __future__ import annotations

import re


def release_label(version: str | None) -> str:
    text = str(version or "").strip()
    match = re.match(r"^(\d+)\.(\d+)\.(\d+)", text)
    if not match:
        return text or "?"
    major, minor, patch = match.groups()
    return f"{major}.{minor}{patch}"


def release_channel(version: str | None) -> str:
    text = str(version or "").lower()
    if "beta" in text:
        return "BETA"
    if "alpha" in text:
        return "ALPHA"
    return ""
