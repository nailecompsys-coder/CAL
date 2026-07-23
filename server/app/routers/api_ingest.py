"""Service-to-service ingest for Desk (fax triage) → CAL schedules / surgical cases.

Auth: Authorization: Bearer <CAL_INGEST_TOKEN> (or CAL_API_TOKEN).
Does not mark anything in Kno2.
"""

from __future__ import annotations

import os
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..admin_surgical_schedule_service import add_surgical_case, surgery_fields
from ..database import get_db
from ..ingest_resolve import resolve_surgeon
from ..ingest_schedule_service import ingest_surgeon_schedule
from ..models import Surgeon

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


class SurgicalCaseIn(BaseModel):
    surgeon_name: str | None = None
    surgeon_id: int | None = None
    case_date: str
    start_time: str = "08:00"
    end_time: str = ""
    patient_name: str
    patient_dob: str = ""
    patient_phone: str = ""
    procedure: str = ""
    room_text: str = ""
    location_id: int | None = None
    status: str = "scheduled"
    notes: str = ""


class SurgicalCasesBatch(BaseModel):
    source: str = "desk"
    source_fax_id: int | None = None
    source_message_id: str | None = None
    notify: bool = False
    cases: list[SurgicalCaseIn] = Field(default_factory=list)


class OrCaseIn(BaseModel):
    case_date: str | None = None
    start_time: str | None = None
    patient_name: str
    procedure: str = ""
    room: str = ""


class OrBlockIn(BaseModel):
    session: str = "am"
    room: str | None = None
    rooms: list[str] = Field(default_factory=list)
    block_start: str | None = None
    block_end: str | None = None
    cases: list[OrCaseIn] = Field(default_factory=list)


class ClinicSlotIn(BaseModel):
    case_date: str | None = None
    start_time: str | None = None
    patient_name: str = ""
    procedure: str = ""
    site_raw: str | None = None
    visit_type: str | None = None


class ClinicRotationIn(BaseModel):
    session: str = "pm"
    site_raw: str | None = None
    slots: list[ClinicSlotIn] = Field(default_factory=list)


class SurgeonScheduleIn(BaseModel):
    surgeon_name: str | None = None
    surgeon_raw: str | None = None
    start_date: str | None = None
    end_date: str | None = None
    or_block: OrBlockIn | None = None
    clinic_rotation: ClinicRotationIn | None = None


class SurgeonScheduleBatch(BaseModel):
    source: str = "desk"
    source_fax_id: int | None = None
    source_message_id: str | None = None
    notify: bool = False
    surgeons: list[SurgeonScheduleIn] = Field(default_factory=list)


@router.post("/surgical-cases")
def ingest_surgical_cases(
    body: SurgicalCasesBatch,
    db: Session = Depends(get_db),
    _: None = Depends(require_ingest_token),
) -> dict[str, Any]:
    """Legacy: OR patients only as surgical_cases (no Block OR / clinic lanes)."""
    if not body.cases:
        raise HTTPException(400, "cases required")
    if len(body.cases) > 200:
        raise HTTPException(400, "too many cases (max 200)")

    created: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []

    for idx, item in enumerate(body.cases):
        surgeon = None
        if item.surgeon_id:
            surgeon = db.query(Surgeon).filter(Surgeon.id == item.surgeon_id).first()
        if not surgeon:
            surgeon = resolve_surgeon(db, item.surgeon_name)
        if not surgeon:
            errors.append(
                {
                    "index": idx,
                    "patient_name": item.patient_name,
                    "error": f"surgeon not found: {item.surgeon_name or item.surgeon_id}",
                }
            )
            continue

        loc_id = ""
        if item.location_id:
            loc_id = str(item.location_id)
        else:
            from ..ingest_resolve import resolve_or_location
            from datetime import date as date_cls

            case_day = None
            try:
                case_day = date_cls.fromisoformat(str(item.case_date)[:10])
            except ValueError:
                case_day = None
            loc = resolve_or_location(
                db,
                item.room_text,
                surgeon_id=surgeon.id,
                day=case_day,
            )
            # Never fall back to clinic locations (e.g. HP-CL) for OR cases
            if loc:
                loc_id = str(loc.id)

        note_parts = [item.notes.strip()] if item.notes.strip() else []
        if body.source_fax_id:
            note_parts.append(f"Desk fax #{body.source_fax_id}")
        if body.source_message_id:
            note_parts.append(f"Kno2 {body.source_message_id}")
        note_parts.append(f"source={body.source}")
        notes = " · ".join(note_parts)

        try:
            fields = surgery_fields(
                surgeon.id,
                item.case_date,
                item.start_time or "08:00",
                item.patient_name,
                item.procedure or "TBD",
                item.end_time or "",
                item.patient_dob or "",
                item.patient_phone or "",
                loc_id,
                item.room_text or "",
                item.status or "scheduled",
                notes,
            )
            surgical_case, _warn = add_surgical_case(db, fields, notify=body.notify)
            created.append(
                {
                    "id": surgical_case.id,
                    "surgeon_id": surgical_case.surgeon_id,
                    "case_date": str(surgical_case.date),
                    "patient_name": surgical_case.patient_name,
                    "start_time": surgical_case.start_time.strftime("%H:%M"),
                }
            )
        except ValueError as exc:
            errors.append({"index": idx, "patient_name": item.patient_name, "error": str(exc)})
        except Exception as exc:  # noqa: BLE001
            errors.append({"index": idx, "patient_name": item.patient_name, "error": str(exc)})

    return {
        "ok": len(errors) == 0,
        "created": created,
        "created_count": len(created),
        "error_count": len(errors),
        "errors": errors,
    }


@router.post("/surgeon-schedule")
def ingest_surgeon_schedule_route(
    body: SurgeonScheduleBatch,
    db: Session = Depends(get_db),
    _: None = Depends(require_ingest_token),
) -> dict[str, Any]:
    """Full Desk schedule publish: Block OR + cases + clinic day lanes."""
    if not body.surgeons:
        raise HTTPException(400, "surgeons required")
    if len(body.surgeons) > 50:
        raise HTTPException(400, "too many surgeons (max 50)")

    payload = [s.model_dump() for s in body.surgeons]
    # Normalize names for resolver
    for row in payload:
        if not row.get("surgeon_name") and row.get("surgeon_raw"):
            row["surgeon_name"] = row["surgeon_raw"]

    return ingest_surgeon_schedule(
        db,
        surgeons=payload,
        source=body.source or "desk",
        source_fax_id=body.source_fax_id,
        source_message_id=body.source_message_id,
        notify=body.notify,
    )
