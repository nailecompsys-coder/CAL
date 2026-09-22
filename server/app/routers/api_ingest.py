"""Service-to-service Desk ingest using the visual fax SOT path only.

Auth: Authorization: Bearer <CAL_INGEST_TOKEN> (or CAL_API_TOKEN).
Desk must send reviewed PNG/OCR rows. Legacy parser payloads are retired and
cannot write CAL schedules.
"""

from __future__ import annotations

import os
import subprocess
from datetime import date, time
from typing import Any

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..database import get_db
from ..fax_ingest_engine import ReviewedFaxRow, stage_reviewed_rows
from ..fax_pdf_intake import prepare_fax_pdf

router = APIRouter(prefix="/api/ingest", tags=["ingest"])


def _ingest_token() -> str:
    return (os.environ.get("CAL_INGEST_TOKEN") or os.environ.get("CAL_API_TOKEN") or "").strip()


def require_ingest_token(authorization: str | None = Header(default=None)) -> None:
    expected = _ingest_token()
    if not expected:
        raise HTTPException(503, "CAL ingest token not configured")
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "Bearer token required")
    got = authorization[7:].strip()
    if not got or got != expected:
        raise HTTPException(403, "Invalid ingest token")


class VisualFaxRowIn(BaseModel):
    fax_id: int | None = None
    page: int = 0
    surgeon_initials: str
    surgeon_name: str | None = None
    case_date: str
    start_time: str | None = None
    row_type: str
    room: str = ""
    patient_name: str
    procedure: str = ""
    visual_confidence: str = "reviewed"
    placement_status: str = "reviewed"
    notes: str = ""


class VisualScheduleBatch(BaseModel):
    source_fax_id: int
    source_label: str = "Desk visual PNG SOT"
    backup_label: str | None = None
    rows: list[VisualFaxRowIn] = Field(default_factory=list)


@router.post("/fax/{source_fax_id:int}/prepare")
def prepare_fax_route(
    source_fax_id: int,
    fax_pdf: UploadFile = File(...),
    source_label: str = Form("Kno2 raw fax PDF"),
    db: Session = Depends(get_db),
    _: None = Depends(require_ingest_token),
) -> dict[str, Any]:
    """Persist and verify a raw fax PDF. This endpoint cannot write schedules."""
    try:
        result = prepare_fax_pdf(
            db,
            external_fax_id=source_fax_id,
            original_filename=fax_pdf.filename or "fax.pdf",
            source=fax_pdf.file,
            source_label=source_label,
        )
        db.commit()
        return {"ok": True, "result": result}
    except ValueError as exc:
        db.rollback()
        raise HTTPException(400, str(exc)) from exc
    except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
        db.rollback()
        raise HTTPException(500, f"Fax preparation failed: {exc}") from exc


def _parse_day(raw: str) -> date:
    try:
        return date.fromisoformat(str(raw)[:10])
    except ValueError as exc:
        raise HTTPException(400, f"Invalid case_date: {raw}") from exc


def _parse_clock(raw: str | None) -> time | None:
    if not raw:
        return None
    text = str(raw).strip()
    if not text:
        return None
    try:
        parts = text.split(":")
        if len(parts) == 2:
            return time(int(parts[0]), int(parts[1]))
        digits = "".join(ch for ch in text if ch.isdigit())
        if len(digits) == 4:
            return time(int(digits[:2]), int(digits[2:]))
    except ValueError as exc:
        raise HTTPException(400, f"Invalid start_time: {raw}") from exc
    raise HTTPException(400, f"Invalid start_time: {raw}")


def _visual_row(item: VisualFaxRowIn) -> ReviewedFaxRow:
    row_type = (item.row_type or "").strip().lower()
    if row_type not in {"surgical", "clinic"}:
        raise HTTPException(400, "row_type must be surgical or clinic")
    return ReviewedFaxRow(
        page=item.page,
        surgeon_initials=item.surgeon_initials.strip().upper(),
        surgeon_name=(item.surgeon_name or "").strip() or None,
        case_date=_parse_day(item.case_date),
        start_time=_parse_clock(item.start_time),
        row_type=row_type,
        room=item.room or "",
        patient_name=item.patient_name.strip(),
        procedure=item.procedure or "",
    )


@router.post("/visual-schedule")
def ingest_visual_schedule_route(
    body: VisualScheduleBatch,
    db: Session = Depends(get_db),
    _: None = Depends(require_ingest_token),
) -> dict[str, Any]:
    """Desk reviewed-PNG/OCR staging path.

    This route deliberately cannot write schedule cards, legacy schedules, or
    notifications. It records facts and returns placement decisions only.
    """
    if not body.rows:
        raise HTTPException(400, "rows required")
    if len(body.rows) > 1000:
        raise HTTPException(400, "too many rows (max 1000)")
    rows = [_visual_row(item) for item in body.rows]
    fax_ids = {item.fax_id or body.source_fax_id for item in body.rows}
    if fax_ids != {body.source_fax_id}:
        raise HTTPException(400, "all rows must match source_fax_id")
    try:
        result = stage_reviewed_rows(
            db,
            external_fax_id=body.source_fax_id,
            source_label=body.source_label,
            rows=rows,
        )
        db.commit()
    except ValueError as exc:
        db.rollback()
        raise HTTPException(400, str(exc)) from exc
    return {"ok": True, "result": result}


@router.post("/surgical-cases")
def retired_surgical_cases_route(_: None = Depends(require_ingest_token)) -> None:
    raise HTTPException(
        410,
        "Retired. Desk must use /api/ingest/visual-schedule with reviewed PNG/OCR rows.",
    )


@router.post("/surgeon-schedule")
def retired_surgeon_schedule_route(_: None = Depends(require_ingest_token)) -> None:
    raise HTTPException(
        410,
        "Retired. Desk must use /api/ingest/visual-schedule with reviewed PNG/OCR rows.",
    )
