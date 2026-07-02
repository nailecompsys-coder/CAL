"""Filesystem paths for the CAL server package.

Keep runtime paths based on this file instead of the process working directory.
That lets the server survive the later move from repo root files into server/.
"""
from pathlib import Path


APP_DIR = Path(__file__).resolve().parent
SERVER_ROOT = APP_DIR.parent
STATIC_DIR = APP_DIR / "static"
TEMPLATES_DIR = APP_DIR / "templates"
UPLOADS_DIR = STATIC_DIR / "uploads"
VERSION_FILE = SERVER_ROOT / "VERSION"
