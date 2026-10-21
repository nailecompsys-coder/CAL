"""Service-to-service staging for structured Desk extractor schedule rows.

Auth: Authorization: Bearer <CAL_INGEST_TOKEN> (or CAL_API_TOKEN).
Desk must send reviewed structured rows. Legacy parser payloads are retired and
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
from ..fax_preview import preview_reviewed_rows
from ..fax_restore_service import restore_fax_snapshot
from ..fax_snapshot_service import apply_staged_snapshot

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
    source_row_number: int | None = None
    surgeon_initials: str
    surgeon_name: str | None = None
    case_date: str | None = None
    start_time: str | None = None
    row_type: str
    room: str = ""
    patient_name: str
    procedure: str = ""
    visual_confidence: str = "reviewed"
    placement_status: str = "reviewed"
    notes: str = ""


class FaxCoverageIn(BaseModel):
    surgeon_initials: str
    case_date: str


class VisualScheduleBatch(BaseModel):
    source_fax_id: int
    source_label: str = "Desk structured fax extraction"
    extractor_name: str = "structured_extract"
    extractor_version: str | None = None
    extractor_request_id: str | None = None
    backup_label: str | None = None
    surgeon_scope: list[str] = Field(default_factory=list)
    coverage: list[FaxCoverageIn] = Field(default_factory=list)
    rows: list[VisualFaxRowIn] = Field(default_factory=list)


class SnapshotApplyIn(BaseModel):
    run_id: int
    confirm_authoritative_snapshot: bool = False


class SnapshotRestoreIn(BaseModel):
    confirm_restore: bool = False


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


def _visual_row(item: VisualFaxRowIn, *, allow_unresolved: bool = False) -> ReviewedFaxRow:
    row_type = (item.row_type or "").strip().lower()
    if row_type not in {"surgical", "clinic"}:
        raise HTTPException(400, "row_type must be surgical or clinic")
    case_date: date | str
    start_time: time | str | None
    if allow_unresolved:
        raw_day = str(item.case_date or "").strip()
        try:
            case_date = _parse_day(raw_day)
        except HTTPException:
            case_date = raw_day
        try:
            start_time = _parse_clock(item.start_time)
        except HTTPException:
            start_time = str(item.start_time or "").strip() or None
    else:
        case_date = _parse_day(item.case_date or "")
        start_time = _parse_clock(item.start_time)
    return ReviewedFaxRow(
        page=item.page,
        surgeon_initials=item.surgeon_initials.strip().upper(),
        surgeon_name=(item.surgeon_name or "").strip() or None,
        case_date=case_date,
        start_time=start_time,
        row_type=row_type,
        room=item.room or "",
        patient_name=item.patient_name.strip(),
        procedure=item.procedure or "",
        extraction_flags=((item.notes or "").strip() or "flagged") if item.visual_confidence == "flagged" else None,
        source_row_number=item.source_row_number,
    )


def _upcoming_rows(
    body: VisualScheduleBatch, *, allow_unresolved: bool = False
) -> tuple[list[ReviewedFaxRow], int]:
    if not body.rows:
        raise HTTPException(400, "rows required")
    if len(body.rows) > 1000:
        raise HTTPException(400, "too many rows (max 1000)")
    fax_ids = {item.fax_id or body.source_fax_id for item in body.rows}
    if fax_ids != {body.source_fax_id}:
        raise HTTPException(400, "all rows must match source_fax_id")
    parsed = [_visual_row(item, allow_unresolved=allow_unresolved) for item in body.rows]
    return parsed, 0


@router.post("/preview")
def preview_visual_schedule_route(
    body: VisualScheduleBatch,
    db: Session = Depends(get_db),
    _: None = Depends(require_ingest_token),
) -> dict[str, Any]:
    """Label each upcoming fax row match / addition / fail against the live schedule. Writes nothing."""
    rows, skipped_past = _upcoming_rows(body)
    if not rows:
        return {"ok": True, "result": {"rows": [], "calOnly": [], "skippedPast": skipped_past}}
    try:
        result = preview_reviewed_rows(db, external_fax_id=body.source_fax_id, source_label=body.source_label, rows=rows)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"ok": True, "result": {**result, "skippedPast": skipped_past}}


@router.post("/visual-schedule")
def ingest_visual_schedule_route(
    body: VisualScheduleBatch,
    db: Session = Depends(get_db),
    _: None = Depends(require_ingest_token),
) -> dict[str, Any]:
    """Desk structured-extractor staging path.

    This route deliberately cannot write schedule cards, legacy schedules, or
    notifications. It records facts and returns placement decisions only.
    """
    rows, skipped_past = _upcoming_rows(body, allow_unresolved=True)
    if not rows:
        return {"ok": True, "result": {"rows": 0, "skippedPast": skipped_past, "writeMode": "staging_only"}}
    try:
        result = stage_reviewed_rows(
            db,
            external_fax_id=body.source_fax_id,
            source_label=body.source_label,
            rows=rows,
            surgeon_scope=body.surgeon_scope,
            extractor_name=body.extractor_name,
            extractor_version=body.extractor_version,
            extractor_request_id=body.extractor_request_id,
            coverage=[
                (item.surgeon_initials, _parse_day(item.case_date))
                for item in body.coverage
            ],
        )
        db.commit()
    except ValueError as exc:
        db.rollback()
        raise HTTPException(400, str(exc)) from exc
    return {"ok": True, "result": {**result, "skippedPast": skipped_past}}


@router.post("/fax/{source_fax_id:int}/apply-snapshot")
def apply_fax_snapshot_route(
    source_fax_id: int,
    body: SnapshotApplyIn,
    db: Session = Depends(get_db),
    _: None = Depends(require_ingest_token),
) -> dict[str, Any]:
    """Backup and apply a reviewed daily snapshot to existing cards only."""
    if not body.confirm_authoritative_snapshot:
        raise HTTPException(400, "confirm_authoritative_snapshot is required")
    try:
        result = apply_staged_snapshot(
            db,
            source_fax_id=source_fax_id,
            run_id=body.run_id,
        )
    except ValueError as exc:
        db.rollback()
        raise HTTPException(400, str(exc)) from exc
    return {"ok": True, "result": result}


@router.post("/fax/{source_fax_id:int}/restore-snapshot")
def restore_fax_snapshot_route(
    source_fax_id: int,
    body: SnapshotRestoreIn,
    db: Session = Depends(get_db),
    _: None = Depends(require_ingest_token),
) -> dict[str, Any]:
    """Put back the card lines saved before this fax was sent to the calendar."""
    if not body.confirm_restore:
        raise HTTPException(400, "confirm_restore is required")
    try:
        result = restore_fax_snapshot(db, source_fax_id=source_fax_id)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(400, str(exc)) from exc
    return {"ok": True, "result": result}


@router.post("/surgical-cases")
def retired_surgical_cases_route(_: None = Depends(require_ingest_token)) -> None:
    raise HTTPException(
        410,
        "Retired. Desk must use /api/ingest/visual-schedule with structured extractor rows.",
    )


@router.post("/surgeon-schedule")
def retired_surgeon_schedule_route(_: None = Depends(require_ingest_token)) -> None:
    raise HTTPException(
        410,
        "Retired. Desk must use /api/ingest/visual-schedule with structured extractor rows.",
    )
