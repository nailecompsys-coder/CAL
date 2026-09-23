"""Revert Desk fax ingest by provenance tag (Desk fax #N in notes)."""

from __future__ import annotations

import json
import re
from typing import Any

from sqlalchemy.orm import Session

from .models import (
    AdminNotification,
    ClinicSchedule,
    ORBlockAssignment,
    ScheduleChangeEvent,
    SurgicalCase,
)

_FAX_RE = re.compile(r"Desk fax\s*#\s*(\d+)", re.IGNORECASE)


def desk_fax_ids_in_text(text: str | None) -> set[int]:
    return {int(m.group(1)) for m in _FAX_RE.finditer(text or "")}


def revert_desk_faxes(db: Session, fax_ids: list[int] | set[int]) -> dict[str, Any]:
    """Remove schedule rows written by the given Desk fax ids.

    - Cancels surgical cases tagged with those faxes
    - Deletes clinic schedule rows tagged with those faxes
    - Deletes Block OR assignments tagged with those faxes
    - Does NOT delete Block OR capacity cards
    - Clears matching ingest/schedule-flag notifications
    """
    wanted = {int(x) for x in fax_ids}
    if not wanted:
        return {"ok": False, "error": "no fax ids", "fax_ids": []}

    cases_cancelled = 0
    clinics_deleted = 0
    assigns_deleted = 0
    notifs_deleted = 0
    flags_deleted = 0

    for case in db.query(SurgicalCase).filter(SurgicalCase.notes.isnot(None)).all():
        ids = desk_fax_ids_in_text(case.notes)
        if not ids.intersection(wanted):
            continue
        if (case.status or "") != "cancelled":
            case.status = "cancelled"
            cases_cancelled += 1
        from .schedule_activity_normalization import normalize_surgical_case_card
        normalize_surgical_case_card(db, case)
        # Drop block link so cancelled fax cases do not keep pills alive.
        case.or_block_instance_id = None

    for row in db.query(ClinicSchedule).filter(ClinicSchedule.notes.isnot(None)).all():
        ids = desk_fax_ids_in_text(row.notes)
        if not ids.intersection(wanted):
            continue
        db.delete(row)
        clinics_deleted += 1

    for assign in db.query(ORBlockAssignment).filter(ORBlockAssignment.note.isnot(None)).all():
        ids = desk_fax_ids_in_text(assign.note)
        if not ids.intersection(wanted):
            continue
        db.delete(assign)
        assigns_deleted += 1

    # Assignments with empty note but only fax cases for that surgeon/block — already
    # cancelled above; drop orphan assigns with zero remaining active cases.
    orphans = (
        db.query(ORBlockAssignment)
        .all()
    )
    for assign in orphans:
        active = (
            db.query(SurgicalCase)
            .filter(
                SurgicalCase.or_block_instance_id == assign.block_instance_id,
                SurgicalCase.surgeon_id == assign.surgeon_id,
                SurgicalCase.status != "cancelled",
            )
            .count()
        )
        if active:
            continue
        # Only remove if this surgeon/block had a cancelled fax case from wanted set.
        had_fax = (
            db.query(SurgicalCase)
            .filter(
                SurgicalCase.or_block_instance_id == assign.block_instance_id,
                SurgicalCase.surgeon_id == assign.surgeon_id,
                SurgicalCase.status == "cancelled",
                SurgicalCase.notes.isnot(None),
            )
            .all()
        )
        if not any(desk_fax_ids_in_text(c.notes).intersection(wanted) for c in had_fax):
            continue
        db.delete(assign)
        assigns_deleted += 1

    for row in db.query(AdminNotification).filter(
        AdminNotification.kind.in_(("ingest_correction", "schedule_flag"))
    ).all():
        try:
            payload = json.loads(row.payload or "{}") if row.payload else {}
        except (TypeError, ValueError):
            payload = {}
        src = payload.get("sourceFaxId")
        try:
            src_i = int(src) if src is not None else None
        except (TypeError, ValueError):
            src_i = None
        body_ids = desk_fax_ids_in_text(row.body)
        if src_i in wanted or body_ids.intersection(wanted):
            db.delete(row)
            notifs_deleted += 1

    for row in db.query(ScheduleChangeEvent).filter(
        ScheduleChangeEvent.event_type == "desk_or_schedule_flag"
    ).all():
        try:
            payload = json.loads(row.payload or "{}") if row.payload else {}
        except (TypeError, ValueError):
            payload = {}
        src = payload.get("sourceFaxId")
        try:
            src_i = int(src) if src is not None else None
        except (TypeError, ValueError):
            src_i = None
        body_ids = desk_fax_ids_in_text(row.body) | desk_fax_ids_in_text(payload.get("source"))
        ocr = payload.get("ocrRows") if isinstance(payload.get("ocrRows"), list) else []
        for item in ocr:
            try:
                if int(item.get("sourceFaxId")) in wanted:
                    body_ids.add(int(item.get("sourceFaxId")))
            except (TypeError, ValueError):
                pass
        if src_i in wanted or body_ids.intersection(wanted):
            db.delete(row)
            flags_deleted += 1

    db.commit()
    return {
        "ok": True,
        "fax_ids": sorted(wanted),
        "cases_cancelled": cases_cancelled,
        "clinics_deleted": clinics_deleted,
        "assignments_deleted": assigns_deleted,
        "notifications_deleted": notifs_deleted,
        "flags_deleted": flags_deleted,
    }
