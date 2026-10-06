"""Verify fax row ownership against the rendered, OCR'd source pages.

The surgeon header starts a section that continues until the next header.
An extracted row is never allowed to choose its own surgeon independently of
that section.  Unreadable headers fail closed before schedule data is changed.
"""

from __future__ import annotations

import re
from pathlib import Path

from sqlalchemy.orm import Session

from .models import FaxDocument, FaxPage, Surgeon


HEADER = re.compile(r"\bSurgeon\s*:\s*([^\r\n]+)", re.IGNORECASE)


def _words(value: str) -> list[str]:
    return re.findall(r"[a-z]+", value.lower())


def _header_surgeon(header: str, surgeons: list[Surgeon]) -> Surgeon:
    tokens = set(_words(header.split(" MD")[0]))
    matches = [surgeon for surgeon in surgeons if (surgeon.last_name or "").lower() in tokens]
    if len(matches) > 1:
        matches = [surgeon for surgeon in matches if (surgeon.first_name or "").lower() in tokens]
    if len(matches) != 1:
        raise ValueError("Fax surgeon header does not match exactly one active surgeon.")
    return matches[0]


def page_owners(db: Session, document: FaxDocument) -> dict[int, str]:
    """Return the surgeon initials responsible for each numbered source page."""
    if not document.source_sha256 or not document.page_count:
        raise ValueError("Fax PDF must be prepared into PNG and OCR pages first.")
    pages = db.query(FaxPage).filter(FaxPage.fax_document_id == document.id).order_by(FaxPage.page_number).all()
    if len(pages) != document.page_count or [p.page_number for p in pages] != list(range(1, document.page_count + 1)):
        raise ValueError("Fax PNG/OCR page set is incomplete.")
    surgeons = db.query(Surgeon).filter(Surgeon.is_active == True).all()  # noqa: E712
    owners: dict[int, str] = {}
    current: str | None = None
    for page in pages:
        path = Path(page.ocr_text_path or "")
        if not path.is_file():
            raise ValueError(f"Fax OCR page {page.page_number} is missing.")
        text = path.read_text(errors="replace")
        headers = HEADER.findall(text)
        if len(headers) > 1:
            raise ValueError(f"Fax page {page.page_number} has multiple surgeon headers.")
        if headers:
            surgeon = _header_surgeon(headers[0], surgeons)
            current = f"{(surgeon.first_name or '')[:1]}{(surgeon.last_name or '')[:1]}".upper()
        if current:
            owners[page.page_number] = current
    if not owners:
        raise ValueError("No surgeon headers were found in the fax OCR pages.")
    return owners
