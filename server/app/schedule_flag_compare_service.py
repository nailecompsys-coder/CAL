"""Schedule-flag compare: CAL Block OR state vs fax OCR rows."""

from __future__ import annotations

import json
import re
from datetime import date
from typing import Any

from sqlalchemy.orm import Session, joinedload

from .models import ORBlockAssignment, ORBlockInstance, ScheduleChangeEvent, Surgeon, SurgicalCase
from .or_block_service import ACTIVE_BLOCK_STATUSES

_FAX_RE = re.compile(r"Desk fax\s*#\s*(\d+)", re.IGNORECASE)


def _as_date(value) -> date | None:
    if isinstance(value, date):
        return value
    raw = str(value or "").strip()[:10]
    if not raw:
        return None
    try:
        return date.fromisoformat(raw)
    except ValueError:
        return None


def desk_fax_id_from_text(text: str | None) -> int | None:
    match = _FAX_RE.search(text or "")
    if not match:
        return None
    try:
        return int(match.group(1))
    except ValueError:
        return None


def serialize_ocr_rows(cases: list[dict[str, Any]], *, source_fax_id: int | None) -> list[dict[str, Any]]:
    rows = []
    for case in cases:
        rows.append({
            "patientName": (case.get("patient_name") or "").strip(),
            "caseDate": (case.get("case_date") or "").strip()[:10],
            "startTime": (case.get("start_time") or "").strip(),
            "room": (case.get("room") or "").strip(),
            "procedure": ((case.get("procedure") or "").strip())[:120],
            "surgeonRaw": (case.get("surgeon_raw") or case.get("surgeon_name") or "").strip(),
            "sourceFaxId": source_fax_id,
        })
    return rows


def flag_event_payload(row: ScheduleChangeEvent) -> dict[str, Any]:
    try:
        return json.loads(row.payload or "{}") if row.payload else {}
    except (TypeError, ValueError):
        return {}


def build_schedule_flag_compare(db: Session, event_id: int) -> dict[str, Any] | None:
    row = db.get(ScheduleChangeEvent, event_id)
    if row is None or (row.event_type or "") != "desk_or_schedule_flag":
        return None
    payload = flag_event_payload(row)
    surgeon = db.get(Surgeon, row.surgeon_id) if row.surgeon_id else None
    day = _as_date(payload.get("date")) or row.date
    try:
        block_id = int(payload["blockId"]) if payload.get("blockId") is not None else None
    except (TypeError, ValueError):
        block_id = None

    flagged_block = None
    if block_id:
        flagged_block = (
            db.query(ORBlockInstance)
            .options(joinedload(ORBlockInstance.location))
            .filter(ORBlockInstance.id == block_id)
            .first()
        )

    cal_assignments: list[dict[str, Any]] = []
    if surgeon and day:
        links = (
            db.query(ORBlockAssignment, ORBlockInstance)
            .join(ORBlockInstance, ORBlockAssignment.block_instance_id == ORBlockInstance.id)
            .options(joinedload(ORBlockInstance.location))
            .filter(
                ORBlockAssignment.surgeon_id == surgeon.id,
                ORBlockInstance.date == day,
                ORBlockInstance.status.in_(ACTIVE_BLOCK_STATUSES),
            )
            .order_by(ORBlockInstance.start_time, ORBlockInstance.id)
            .all()
        )
        for assign, block in links:
            loc = block.location
            cal_assignments.append({
                "blockId": block.id,
                "location": (loc.abbreviation or loc.name) if loc else "OR",
                "session": (block.session or "").upper(),
                "start": block.start_time.strftime("%H:%M") if block.start_time else "",
                "end": block.end_time.strftime("%H:%M") if block.end_time else "",
                "assignStart": assign.start_time.strftime("%H:%M") if assign.start_time else "",
                "flagged": block.id == block_id,
            })

    cal_cases: list[dict[str, Any]] = []
    if day:
        case_filters = [SurgicalCase.date == day, SurgicalCase.status != "cancelled"]
        id_filters = []
        if surgeon:
            id_filters.append(SurgicalCase.surgeon_id == surgeon.id)
            id_filters.append(SurgicalCase.assisting_surgeon_id == surgeon.id)
        if block_id:
            id_filters.append(SurgicalCase.or_block_instance_id == block_id)
        from sqlalchemy import or_ as sql_or
        q = db.query(SurgicalCase).filter(*case_filters)
        if id_filters:
            q = q.filter(sql_or(*id_filters))
        for case in q.order_by(SurgicalCase.start_time, SurgicalCase.id).all():
            primary = db.get(Surgeon, case.surgeon_id)
            assist = db.get(Surgeon, case.assisting_surgeon_id) if case.assisting_surgeon_id else None
            cal_cases.append({
                "id": case.id,
                "startTime": case.start_time.strftime("%H:%M") if case.start_time else "",
                "patientName": case.patient_name,
                "room": case.room_text or "",
                "procedure": (case.procedure or "")[:100],
                "blockId": case.or_block_instance_id,
                "primary": primary.initials if primary else "",
                "assist": assist.initials if assist else "",
                "faxId": desk_fax_id_from_text(case.notes),
                "notes": case.notes or "",
                "onFlaggedBlock": case.or_block_instance_id == block_id,
            })

    ocr_rows = payload.get("ocrRows") if isinstance(payload.get("ocrRows"), list) else []
    source_fax_id = payload.get("sourceFaxId") or desk_fax_id_from_text(payload.get("source"))

    flagged_loc = ""
    if flagged_block and flagged_block.location:
        flagged_loc = flagged_block.location.abbreviation or flagged_block.location.name or ""

    return {
        "eventId": row.id,
        "body": row.body or "",
        "warnings": payload.get("warnings") if isinstance(payload.get("warnings"), list) else [],
        "date": day.isoformat() if day else None,
        "surgeonId": surgeon.id if surgeon else None,
        "surgeonName": surgeon.full_name if surgeon else "",
        "surgeonInitials": (surgeon.initials or "") if surgeon else "",
        "blockId": block_id,
        "blockLabel": (
            f"{flagged_loc} "
            f"{(flagged_block.session or '').upper()} "
            f"{flagged_block.start_time.strftime('%H:%M') if flagged_block and flagged_block.start_time else ''}"
            f"-{flagged_block.end_time.strftime('%H:%M') if flagged_block and flagged_block.end_time else ''}"
        ).strip() if flagged_block else "",
        "sourceFaxId": source_fax_id,
        "calAssignments": cal_assignments,
        "calCases": cal_cases,
        "ocrRows": ocr_rows,
        "hrefBlockOr": f"/admin/block-or?block_id={block_id}" if block_id else "/admin/block-or",
    }


def enrich_flag_list_row(db: Session, row: dict[str, Any]) -> dict[str, Any]:
    """Attach compare href + short CAL/OCR blurb for Needs attention cards."""
    event_id = row.get("id")
    href = f"/admin/schedule-flags/{event_id}" if event_id else (row.get("href") or "/admin/block-or")
    out = dict(row)
    out["compareHref"] = href
    out["href"] = href
    payload = row.get("payload") if isinstance(row.get("payload"), dict) else {}
    ocr = payload.get("ocrRows") if isinstance(payload.get("ocrRows"), list) else []
    if ocr:
        bits = []
        for item in ocr[:3]:
            bits.append(
                f"{item.get('startTime') or '—'} {item.get('room') or ''} "
                f"{item.get('patientName') or ''}".strip()
            )
        out["ocrPreview"] = " · ".join(bits)
    else:
        out["ocrPreview"] = ""
    return out
