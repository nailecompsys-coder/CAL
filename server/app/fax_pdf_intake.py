"""Immutable raw-PDF intake and verified page rendering for fax ingest."""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
import uuid
from pathlib import Path
from typing import BinaryIO

from sqlalchemy.orm import Session

from .models import FaxDocument, FaxPage


MAX_FAX_BYTES = 100 * 1024 * 1024
PDF_HEADER = b"%PDF-"


def fax_data_root() -> Path:
    return Path(os.environ.get("CAL_FAX_DATA_DIR", "/var/lib/cal/faxes")).resolve()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _copy_pdf(source: BinaryIO, target: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    header = b""
    with target.open("wb") as output:
        while True:
            chunk = source.read(1024 * 1024)
            if not chunk:
                break
            if not header:
                header = chunk[:5]
            size += len(chunk)
            if size > MAX_FAX_BYTES:
                raise ValueError("Fax PDF exceeds the 100 MB intake limit.")
            digest.update(chunk)
            output.write(chunk)
    if header != PDF_HEADER:
        raise ValueError("Uploaded file is not a valid PDF.")
    return digest.hexdigest(), size


def _pdf_page_count(pdf_path: Path) -> int:
    result = subprocess.run(
        ["pdfinfo", str(pdf_path)], check=True, capture_output=True, text=True,
    )
    match = re.search(r"^Pages:\s+(\d+)\s*$", result.stdout, re.MULTILINE)
    if not match or int(match.group(1)) < 1:
        raise RuntimeError("Could not verify the fax PDF page count.")
    return int(match.group(1))


def _render_and_ocr(pdf_path: Path, workdir: Path, expected_pages: int) -> list[dict]:
    pages_dir = workdir / "pages"
    ocr_dir = workdir / "ocr"
    pages_dir.mkdir()
    ocr_dir.mkdir()
    subprocess.run(
        ["pdftoppm", "-r", "300", "-png", str(pdf_path), str(pages_dir / "page")],
        check=True,
    )
    images = sorted(pages_dir.glob("page-*.png"))
    if len(images) != expected_pages:
        raise RuntimeError(
            f"Rendered page count {len(images)} does not match PDF page count {expected_pages}."
        )
    output: list[dict] = []
    for page_number, image_path in enumerate(images, start=1):
        ocr_base = ocr_dir / f"page-{page_number:03d}"
        subprocess.run(
            ["tesseract", str(image_path), str(ocr_base), "--psm", "6"],
            check=True,
        )
        text_path = ocr_base.with_suffix(".txt")
        if not text_path.exists():
            raise RuntimeError(f"OCR output is missing for fax page {page_number}.")
        output.append({
            "page_number": page_number,
            "image_path": image_path,
            "image_sha256": _sha256(image_path),
            "ocr_text_path": text_path,
            "ocr_text_sha256": _sha256(text_path),
        })
    return output


def prepare_fax_pdf(
    db: Session,
    *,
    external_fax_id: int,
    original_filename: str,
    source: BinaryIO,
    source_label: str = "Kno2 raw fax PDF",
) -> dict:
    """Store, render, OCR, and record a fax without changing schedule data."""
    if external_fax_id < 1:
        raise ValueError("Fax id must be a positive integer.")
    root = fax_data_root()
    root.mkdir(parents=True, exist_ok=True)
    scratch = root / f".prepare-{external_fax_id}-{uuid.uuid4().hex}"
    scratch.mkdir()
    source_pdf = scratch / "source.pdf"
    try:
        source_sha256, source_size = _copy_pdf(source, source_pdf)
        existing = db.query(FaxDocument).filter(
            FaxDocument.external_fax_id == external_fax_id,
        ).one_or_none()
        if existing and existing.source_sha256:
            if existing.source_sha256 != source_sha256:
                raise ValueError("This fax id is already tied to a different immutable PDF.")
            shutil.rmtree(scratch)
            return {
                "faxDocumentId": existing.id,
                "faxId": external_fax_id,
                "status": existing.status,
                "pageCount": existing.page_count or len(existing.pages),
                "sourceSha256": existing.source_sha256,
                "sourceBytes": source_size,
                "idempotent": True,
                "writeMode": "staging_only",
            }

        page_count = _pdf_page_count(source_pdf)
        page_rows = _render_and_ocr(source_pdf, scratch, page_count)
        final_dir = root / str(external_fax_id) / source_sha256
        if final_dir.exists():
            raise RuntimeError("Verified fax artifact directory already exists without a database record.")
        final_dir.parent.mkdir(parents=True, exist_ok=True)
        scratch.rename(final_dir)

        document = existing or FaxDocument(external_fax_id=external_fax_id)
        document.source_label = source_label.strip() or "Kno2 raw fax PDF"
        document.source_sha256 = source_sha256
        document.original_filename = Path(original_filename or "fax.pdf").name
        document.source_path = str(final_dir / "source.pdf")
        document.page_count = page_count
        document.status = "rendered"
        db.add(document)
        db.flush()
        for row in page_rows:
            db.add(FaxPage(
                fax_document_id=document.id,
                page_number=row["page_number"],
                image_path=str(final_dir / "pages" / row["image_path"].name),
                image_sha256=row["image_sha256"],
                ocr_text_path=str(final_dir / "ocr" / row["ocr_text_path"].name),
                ocr_text_sha256=row["ocr_text_sha256"],
            ))
        db.flush()
        return {
            "faxDocumentId": document.id,
            "faxId": external_fax_id,
            "status": "rendered",
            "pageCount": page_count,
            "sourceSha256": source_sha256,
            "sourceBytes": source_size,
            "idempotent": False,
            "writeMode": "staging_only",
        }
    except Exception:
        if scratch.exists():
            shutil.rmtree(scratch)
        raise
