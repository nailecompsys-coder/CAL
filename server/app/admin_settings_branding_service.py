from __future__ import annotations

import os
from os import PathLike

from sqlalchemy.orm import Session


async def save_practice_settings(
    db: Session,
    page_settings,
    practice_name: str,
    logo,
    uploads_dir: str | PathLike[str],
    show_or_patient_procedure_form: bool = False,
    practice_address: str = "",
    practice_city: str = "",
    practice_state: str = "",
    practice_zip: str = "",
    practice_phone: str = "",
    practice_email: str = "",
) -> str:
    if practice_name.strip():
        page_settings.practice_name = practice_name.strip()
    page_settings.practice_address = (practice_address or "").strip() or None
    page_settings.practice_city = (practice_city or "").strip() or None
    page_settings.practice_state = (practice_state or "").strip().upper()[:32] or None
    page_settings.practice_zip = (practice_zip or "").strip() or None
    page_settings.practice_phone = (practice_phone or "").strip() or None
    page_settings.practice_email = (practice_email or "").strip() or None
    page_settings.show_or_patient_procedure_form = show_or_patient_procedure_form
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


def remove_practice_logo(db: Session, page_settings, uploads_dir: str | PathLike[str]) -> None:
    if page_settings.logo_filename:
        path = os.path.join(uploads_dir, page_settings.logo_filename)
        if os.path.exists(path):
            os.remove(path)
        page_settings.logo_filename = None
        db.commit()
