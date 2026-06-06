from __future__ import annotations

import os

from sqlalchemy.orm import Session


async def save_practice_settings(db: Session, page_settings, practice_name: str, logo, uploads_dir: str) -> str:
    if practice_name.strip():
        page_settings.practice_name = practice_name.strip()
    if logo and logo.filename:
        ext = os.path.splitext(logo.filename)[1].lower()
        if ext not in (".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp"):
            return "bad_file"
        save_name = f"logo{ext}"
        contents = await logo.read()
        with open(os.path.join(uploads_dir, save_name), "wb") as file_handle:
            file_handle.write(contents)
        page_settings.logo_filename = save_name
    db.commit()
    return "saved"


def remove_practice_logo(db: Session, page_settings, uploads_dir: str) -> None:
    if page_settings.logo_filename:
        path = os.path.join(uploads_dir, page_settings.logo_filename)
        if os.path.exists(path):
            os.remove(path)
        page_settings.logo_filename = None
        db.commit()
