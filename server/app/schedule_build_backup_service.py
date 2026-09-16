"""Backups for destructive-ish Master Schedule card builds."""
import json
from datetime import UTC, date, datetime, time
from typing import Any

from sqlalchemy import Date, DateTime, Time, inspect, text
from sqlalchemy.orm import Session

from .models import (
    ClinicSchedule,
    ORBlockAssignment,
    ORBlockAuditEvent,
    ORBlockInstance,
    ScheduleBuildBackup,
    SurgicalCase,
)


SNAPSHOT_VERSION = 1


def _dump_value(value: Any) -> Any:
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value


def _row_payload(row: Any) -> dict[str, Any]:
    return {
        column.key: _dump_value(getattr(row, column.key))
        for column in inspect(row.__class__).columns
    }


def _load_value(column, value: Any) -> Any:
    if value is None:
        return None
    if isinstance(column.type, DateTime):
        return datetime.fromisoformat(value)
    if isinstance(column.type, Date):
        return date.fromisoformat(value)
    if isinstance(column.type, Time):
        return time.fromisoformat(value)
    return value


def _model_from_payload(model, payload: dict[str, Any]):
    values = {
        column.key: _load_value(column, payload.get(column.key))
        for column in inspect(model).columns
        if column.key in payload
    }
    return model(**values)


def _bump_pg_sequence(db: Session, table: str, column: str = "id") -> None:
    if db.bind is None or db.bind.dialect.name != "postgresql":
        return
    db.execute(text(
        f"""
        SELECT setval(
            pg_get_serial_sequence('{table}', '{column}'),
            COALESCE((SELECT MAX({column}) FROM {table}), 1),
            true
        )
        """
    ))


def create_schedule_build_backup(
    db: Session,
    *,
    admin_id: int | None,
    start: date,
    end: date,
) -> ScheduleBuildBackup:
    blocks = (
        db.query(ORBlockInstance)
        .filter(ORBlockInstance.date >= start, ORBlockInstance.date <= end)
        .order_by(ORBlockInstance.id)
        .all()
    )
    block_ids = [row.id for row in blocks]
    payload = {
        "version": SNAPSHOT_VERSION,
        "range": {"start": start.isoformat(), "end": end.isoformat()},
        "clinic_schedules": [
            _row_payload(row)
            for row in (
                db.query(ClinicSchedule)
                .filter(ClinicSchedule.date >= start, ClinicSchedule.date <= end)
                .order_by(ClinicSchedule.id)
                .all()
            )
        ],
        "or_block_instances": [_row_payload(row) for row in blocks],
        "or_block_assignments": [
            _row_payload(row)
            for row in (
                db.query(ORBlockAssignment)
                .filter(ORBlockAssignment.block_instance_id.in_(block_ids))
                .order_by(ORBlockAssignment.id)
                .all()
                if block_ids
                else []
            )
        ],
        "or_block_audit_events": [
            _row_payload(row)
            for row in (
                db.query(ORBlockAuditEvent)
                .filter(ORBlockAuditEvent.block_instance_id.in_(block_ids))
                .order_by(ORBlockAuditEvent.id)
                .all()
                if block_ids
                else []
            )
        ],
        # Build Cards may attach existing parked cases to a newly available
        # master OR card. Keep only the scheduling linkage, never patient data.
        "surgical_case_links": [
            {
                "id": row.id,
                "surgeon_id": row.surgeon_id,
                "date": _dump_value(row.date),
                "start_time": _dump_value(row.start_time),
                "location_id": row.location_id,
                "or_block_instance_id": row.or_block_instance_id,
                "room_text": row.room_text,
                "status": row.status,
            }
            for row in (
                db.query(SurgicalCase)
                .filter(SurgicalCase.date >= start, SurgicalCase.date <= end)
                .order_by(SurgicalCase.id)
                .all()
            )
        ],
    }
    backup = ScheduleBuildBackup(
        start_date=start,
        end_date=end,
        created_by_admin_id=admin_id,
        payload_json=json.dumps(payload, separators=(",", ":"), sort_keys=True),
        note="Created automatically before Build Cards.",
    )
    db.add(backup)
    db.commit()
    db.refresh(backup)
    return backup


def revert_schedule_build_backup(
    db: Session,
    *,
    backup_id: int,
    admin_id: int | None,
) -> dict[str, Any]:
    backup = db.get(ScheduleBuildBackup, backup_id)
    if not backup:
        return {"ok": False, "reason": "Backup not found."}
    if backup.reverted_at:
        return {"ok": False, "reason": "This backup was already reverted."}

    start = backup.start_date
    end = backup.end_date
    current_blocks = (
        db.query(ORBlockInstance.id)
        .filter(ORBlockInstance.date >= start, ORBlockInstance.date <= end)
        .all()
    )
    current_block_ids = [row.id for row in current_blocks]
    payload = json.loads(backup.payload_json)
    case_links = {row["id"]: row for row in payload.get("surgical_case_links", [])}
    if current_block_ids and "surgical_case_links" not in payload:
        linked_cases = db.query(SurgicalCase).filter(
            SurgicalCase.or_block_instance_id.in_(current_block_ids)
        ).count()
        if linked_cases:
            return {
                "ok": False,
                "reason": "This older backup cannot safely restore linked surgical cases.",
            }
    if current_block_ids:
        post_backup_case = next(
            (
                row for row in db.query(SurgicalCase).filter(
                    SurgicalCase.or_block_instance_id.in_(current_block_ids)
                ).all()
                if row.id not in case_links
            ),
            None,
        )
        if post_backup_case is not None:
            return {
                "ok": False,
                "reason": "Revert blocked because surgical cases were added after this build.",
            }
    db.query(ClinicSchedule).filter(
        ClinicSchedule.date >= start,
        ClinicSchedule.date <= end,
    ).delete(synchronize_session=False)

    if current_block_ids:
        # Preserve cases while restoring their pre-build linkage after the
        # replacement block instances have been recreated below.
        for case in db.query(SurgicalCase).filter(
            SurgicalCase.or_block_instance_id.in_(current_block_ids)
        ).all():
            case.or_block_instance_id = None
        db.query(ORBlockAuditEvent).filter(
            ORBlockAuditEvent.block_instance_id.in_(current_block_ids)
        ).delete(synchronize_session=False)
        db.query(ORBlockAssignment).filter(
            ORBlockAssignment.block_instance_id.in_(current_block_ids)
        ).delete(synchronize_session=False)
        db.query(ORBlockInstance).filter(
            ORBlockInstance.id.in_(current_block_ids)
        ).delete(synchronize_session=False)

    for row in payload.get("clinic_schedules", []):
        db.add(_model_from_payload(ClinicSchedule, row))
    for row in payload.get("or_block_instances", []):
        db.add(_model_from_payload(ORBlockInstance, row))
    db.flush()
    for row in payload.get("or_block_assignments", []):
        db.add(_model_from_payload(ORBlockAssignment, row))
    for row in payload.get("or_block_audit_events", []):
        db.add(_model_from_payload(ORBlockAuditEvent, row))

    for case_id, link in case_links.items():
        case = db.get(SurgicalCase, case_id)
        if case is None:
            continue
        case.surgeon_id = link.get("surgeon_id")
        case.date = date.fromisoformat(link["date"])
        case.start_time = time.fromisoformat(link["start_time"]) if link.get("start_time") else None
        case.location_id = link.get("location_id")
        case.or_block_instance_id = link.get("or_block_instance_id")
        case.room_text = link.get("room_text")
        case.status = link.get("status")

    backup.reverted_at = datetime.now(UTC).replace(tzinfo=None)
    backup.reverted_by_admin_id = admin_id
    _bump_pg_sequence(db, "clinic_schedules")
    _bump_pg_sequence(db, "or_block_instances")
    _bump_pg_sequence(db, "or_block_assignments")
    _bump_pg_sequence(db, "or_block_audit_events")
    db.commit()
    return {
        "ok": True,
        "from": start.isoformat(),
        "to": end.isoformat(),
        "clinic": len(payload.get("clinic_schedules", [])),
        "blocks": len(payload.get("or_block_instances", [])),
    }
