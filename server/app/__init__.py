"""
Mid Florida Surgical Calendar — production app.

Release string: root **VERSION** file (copied into the image as /app/VERSION).
Clean product version (e.g. `2.0`) — no `+UTC` build suffix.
`/health` and the surgeon PWA footer read the same value. Edit VERSION and rebuild
the image — do not rely on environment variables for the displayed version.
"""

from .paths import VERSION_FILE


def _read_version() -> str:
    if VERSION_FILE.is_file():
        line = VERSION_FILE.read_text(encoding="utf-8").strip().splitlines()
        if line:
            v = line[0].strip()
            if v:
                return v
    return "0.0.0-dev"


__version__ = _read_version()
