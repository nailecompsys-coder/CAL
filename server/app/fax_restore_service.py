"""Photo and warning rows for Send to Calendar.

The photo is taken before the fax writes. Each saved line belongs to that fax.
A warning belongs to the card it is about.
"""

from __future__ import annotations

import json
from datetime import date, datetime, UTC

from sqlalchemy import tuple_
from sqlalchemy.orm import Session

from .models import (
    FaxDocument,
    FaxIngestRow,
    FaxIngestRun,
    FaxRestoreLine,
    FaxRestoreSet,
    ScheduleCard,
    ScheduleCardActivity,
    ScheduleChangeEvent,
    ScheduleWarning,
)

_COPIED_FIELDS = (
    "schedule_card_id",
    "surgeon_id",
    "location_id",
    "activity_date",
    "session",
    "activity_type",
    "start_time",
    "end_time",
    "patient_name",
    "procedure",
    "room_text",
    "source_system",
    "source_record_key",
    "identity_key",
    "fax_ingest_row_id",
    "surgical_case_id",
    "aprima_appointment_id",
    "is_active",
)


def _fax_row_ids(db: Session, source_fax_id: int) -> set[int]:
    return {
        row_id
        for (row_id,) in db.query(FaxIngestRow.id).join(
            FaxIngestRun, FaxIngestRow.run_id == FaxIngestRun.id
        ).join(
            FaxDocument, FaxIngestRun.fax_document_id == FaxDocument.id
        ).filter(FaxDocument.external_fax_id == source_fax_id)
    }


def save_fax_line_photo(
    db: Session,
    *,
    source_fax_id: int,
    run_id: int,
    covered: set[tuple[int, date]],
) -> FaxRestoreSet:
    """Save card lines this fax has not written yet. A later send keeps the first photo."""
    photo = db.query(FaxRestoreSet).filter_by(source_fax_id=source_fax_id).one_or_none()
    if photo and photo.restored_at is not None:
        db.delete(photo)
        db.flush()
        photo = None
    if photo is None:
        photo = FaxRestoreSet(source_fax_id=source_fax_id, run_id=run_id)
        db.add(photo)
        db.flush()
    saved_ids = {
        activity_id
        for (activity_id,) in db.query(FaxRestoreLine.schedule_card_activity_id).filter_by(
            restore_set_id=photo.id
        )
    }
    if not covered:
        return photo
    written_by_this_fax = _fax_row_ids(db, source_fax_id)
    activities = db.query(ScheduleCardActivity).filter(
        tuple_(ScheduleCardActivity.surgeon_id, ScheduleCardActivity.activity_date).in_(list(covered))
    ).all()
    for activity in activities:
        if activity.id in saved_ids or activity.fax_ingest_row_id in written_by_this_fax:
            continue
        db.add(FaxRestoreLine(
            restore_set_id=photo.id,
            schedule_card_activity_id=activity.id,
            **{name: getattr(activity, name) for name in _COPIED_FIELDS},
        ))
    db.flush()
    return photo


def replace_fax_warnings(
    db: Session,
    *,
    source_fax_id: int,
    conflicts: list[dict],
    cards: dict[tuple[int, date, str], ScheduleCard],
) -> int:
    """One warning per fax, card, and problem. The card is the row the warning opens."""
    db.query(ScheduleWarning).filter_by(source_fax_id=source_fax_id).delete(synchronize_session=False)
    db.flush()
    seen: set[tuple[int, int, str]] = set()
    count = 0
    for conflict in conflicts:
        code = str(conflict["code"])
        key = (int(conflict["surgeonId"]), date.fromisoformat(conflict["date"]), conflict["session"])
        card = cards[key]
        unique = (source_fax_id, card.id, code)
        if unique in seen:
            continue
        seen.add(unique)
        detail = {
            name: value
            for name, value in conflict.items()
            if name not in {"code", "surgeonId", "date", "session"}
        }
        db.add(ScheduleWarning(
            source_fax_id=source_fax_id,
            schedule_card_id=card.id,
            warning_code=code,
            detail=json.dumps(detail, sort_keys=True),
        ))
        count += 1
    return count


def restore_fax_snapshot(db: Session, *, source_fax_id: int) -> dict:
    """Put the photo back over the surgeons and days this fax changed."""
    photo = db.query(FaxRestoreSet).filter_by(source_fax_id=source_fax_id).one_or_none()
    if photo is None:
        raise ValueError("This fax has no calendar photo to put back.")
    if photo.restored_at is not None:
        raise ValueError("This fax was already put back.")
    document = db.query(FaxDocument).filter_by(external_fax_id=source_fax_id).one_or_none()
    if document is None:
        raise ValueError("Fax document not found.")

    saved_lines = db.query(FaxRestoreLine).filter_by(restore_set_id=photo.id).all()
    saved_ids: list[int] = []
    restored = 0
    missing = 0
    for saved in saved_lines:
        activity = db.get(ScheduleCardActivity, saved.schedule_card_activity_id)
        if activity is None:
            missing += 1
            continue
        for name in _COPIED_FIELDS:
            setattr(activity, name, getattr(saved, name))
        saved_ids.append(activity.id)
        restored += 1
    db.flush()

    row_ids = list(_fax_row_ids(db, source_fax_id))
    turned_off = 0
    if row_ids:
        query = db.query(ScheduleCardActivity).filter(
            ScheduleCardActivity.fax_ingest_row_id.in_(row_ids),
            ScheduleCardActivity.is_active == True,  # noqa: E712
        )
        if saved_ids:
            query = query.filter(ScheduleCardActivity.id.notin_(saved_ids))
        turned_off = query.update({ScheduleCardActivity.is_active: False}, synchronize_session=False)

    photo.restored_at = datetime.now(UTC).replace(tzinfo=None)
    document.status = "restored"
    for run in db.query(FaxIngestRun).filter_by(fax_document_id=document.id, status="applied"):
        run.status = "restored"
    db.query(ScheduleWarning).filter_by(source_fax_id=source_fax_id).delete(synchronize_session=False)
    db.add(ScheduleChangeEvent(
        event_type="fax_daily_snapshot_restored",
        surgeon_id=None,
        title=f"Fax {source_fax_id} put back",
        body=(
            f"Put fax {source_fax_id} back. "
            f"lines restored={restored}, missing={missing}, turned off={turned_off}."
        ),
        payload=json.dumps({
            "faxId": source_fax_id,
            "restoreSetId": photo.id,
            "linesRestored": restored,
            "linesMissing": missing,
            "linesTurnedOff": turned_off,
        }),
    ))
    db.commit()
    return {
        "ok": True,
        "faxId": source_fax_id,
        "restoreSetId": photo.id,
        "linesRestored": restored,
        "linesMissing": missing,
        "linesTurnedOff": turned_off,
    }
