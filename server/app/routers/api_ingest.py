"""Service-to-service Desk ingest using the visual fax SOT path only.

Auth: Authorization: Bearer <CAL_INGEST_TOKEN> (or CAL_API_TOKEN).
Desk must send reviewed PNG/OCR rows. Legacy parser payloads are retired and
cannot write CAL schedules.
"""

from __future__ import annotations

import os
from datetime import date, time
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..database import get_db
from ..fax_visual_ingest_service import (
    BackupReceipt,
    FaxVisualRow,
    apply_visual_schedule,
    run_local_backup,
)

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


def _visual_row(source_fax_id: int, item: VisualFaxRowIn) -> FaxVisualRow:
    row_type = (item.row_type or "").strip().lower()
    if row_type not in {"surgical", "clinic"}:
        raise HTTPException(400, "row_type must be surgical or clinic")
    return FaxVisualRow(
        fax_id=item.fax_id or source_fax_id,
        page=item.page,
        surgeon_initials=item.surgeon_initials.strip().upper(),
        surgeon_name=(item.surgeon_name or "").strip() or None,
        case_date=_parse_day(item.case_date),
        start_time=_parse_clock(item.start_time),
        row_type=row_type,
        room=item.room or "",
        patient_name=item.patient_name.strip(),
        procedure=item.procedure or "",
        visual_confidence=item.visual_confidence or "reviewed",
        placement_status=item.placement_status or "reviewed",
        notes=item.notes or "",
    )


def _backup_dir() -> Path:
    return Path(os.environ.get("CAL_FAX_BACKUP_DIR") or "/tmp/cal-fax-backups")


@router.post("/visual-schedule")
def ingest_visual_schedule_route(
    body: VisualScheduleBatch,
    db: Session = Depends(get_db),
    _: None = Depends(require_ingest_token),
) -> dict[str, Any]:
    """Desk reviewed-PNG/OCR publish path.

    This is the only Desk schedule write route. It requires a DB backup before
    applying rows and uses the same guardrails as the manual visual ingest CLI.
    """
    if not body.rows:
        raise HTTPException(400, "rows required")
    if len(body.rows) > 1000:
        raise HTTPException(400, "too many rows (max 1000)")
    rows = [_visual_row(body.source_fax_id, item) for item in body.rows]
    fax_ids = {row.fax_id for row in rows}
    if fax_ids != {body.source_fax_id}:
        raise HTTPException(400, "all rows must match source_fax_id")
    backup = run_local_backup(_backup_dir(), label=body.backup_label or f"desk_fax{body.source_fax_id}_visual")
    if not backup.success:
        raise HTTPException(500, f"Backup failed; write refused: {backup.metadata}")
    result = apply_visual_schedule(
        db,
        rows,
        backup=backup,
        source_fax_id=body.source_fax_id,
        source_label=body.source_label or "Desk visual PNG SOT",
    )
    return {
        "ok": True,
        "backup": {
            "label": backup.label,
            "path_or_key": backup.path_or_key,
            "metadata": backup.metadata or {},
        },
        "result": result,
    }


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
