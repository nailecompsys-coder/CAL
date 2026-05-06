"""
Mid Florida Surgical Calendar — production app.

Release string: root **VERSION** file (copied into the image as /app/VERSION).
`/health` and the surgeon PWA footer read the same value. Bump VERSION and rebuild
the image — do not rely on environment variables for the displayed version.
"""
from pathlib import Path


def _read_version() -> str:
    # app/__init__.py → parent is app/, parent's parent is project root (or /app in Docker)
    here = Path(__file__).resolve().parent
    root = here.parent
    vf = root / "VERSION"
    if vf.is_file():
        line = vf.read_text(encoding="utf-8").strip().splitlines()
        if line:
            v = line[0].strip()
            if v:
                return v
    return "0.0.0-dev"


__version__ = _read_version()
