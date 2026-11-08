"""Write transport payloads into normalized schedule columns exactly once."""

from __future__ import annotations

import re
from datetime import date, datetime, time
from zoneinfo import ZoneInfo

from sqlalchemy import func, text
from sqlalchemy.orm import Session

from .migrate_fax_ingest import PRACTICE_TIMEZONE
from .models import (
    FaxDocument,
    FaxIngestRow,
    FaxIngestRun,
    FaxRowDecision,
    Location,
    Meeting,
    ScheduleCard,
    ScheduleCardActivity,
    Surgeon,
)


def _key(value: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", "", (value or "").lower())


def _clock(value: str | None) -> time | None:
    try:
        return time.fromisoformat((value or "").strip())
    except ValueError:
        return None


def _identity(patient_name: str | None, start_time: time | None, activity_type: str) -> str:
    return "|".join((_key(patient_name), start_time.isoformat() if start_time else "", activity_type))


def active_surgical_lines(
    db: Session,
    *,
    surgeon_id: int | None = None,
    surgeon_ids: list[int] | None = None,
    start: date | None = None,
    end: date | None = None,
    day: date | None = None,
    session: str | None = None,
    exclude_activity_id: int | None = None,
) -> list[ScheduleCardActivity]:
    """One row per surgeon, day, and identity. Phones and the website read this list."""
    if surgeon_ids is not None and not surgeon_ids:
        return []
    query = db.query(ScheduleCardActivity).filter(
        ScheduleCardActivity.is_active == True,  # noqa: E712
        ScheduleCardActivity.activity_type == "surgical",
    )
    if surgeon_id is not None:
        query = query.filter(ScheduleCardActivity.surgeon_id == surgeon_id)
    if surgeon_ids is not None:
        query = query.filter(ScheduleCardActivity.surgeon_id.in_(surgeon_ids))
    if day is not None:
        query = query.filter(ScheduleCardActivity.activity_date == day)
    else:
        if start is not None:
            query = query.filter(ScheduleCardActivity.activity_date >= start)
        if end is not None:
            query = query.filter(ScheduleCardActivity.activity_date <= end)
    if session in {"am", "pm"}:
        query = query.filter(ScheduleCardActivity.session == session)
    if exclude_activity_id is not None:
        query = query.filter(ScheduleCardActivity.id != exclude_activity_id)
    rows = query.order_by(
        ScheduleCardActivity.activity_date,
        ScheduleCardActivity.start_time,
        ScheduleCardActivity.id,
    ).all()
    seen: set[tuple] = set()
    kept: list[ScheduleCardActivity] = []
    for row in rows:
        key = (row.surgeon_id, row.activity_date, row.identity_key)
        if key in seen:
            continue
        seen.add(key)
        kept.append(row)
    return kept


_LEAVE_BLOCK = object()


def _upsert_activity(
    db: Session,
    *,
    source_system: str,
    source_record_key: str,
    card: ScheduleCard,
    activity_type: str,
    start_time: time | None,
    end_time: time | None = None,
    patient_name: str,
    procedure: str = "",
    room_text: str | None = None,
    location_id: int | None = None,
    is_active: bool = True,
    fax_ingest_row_id: int | None = None,
    aprima_appointment_id: str | None = None,
    or_block_instance_id: int | None | object = _LEAVE_BLOCK,
) -> ScheduleCardActivity:
    row = db.query(ScheduleCardActivity).filter(
        ScheduleCardActivity.source_system == source_system,
        ScheduleCardActivity.source_record_key == source_record_key,
    ).one_or_none()
    if row is None:
        row = ScheduleCardActivity(source_system=source_system, source_record_key=source_record_key)
        db.add(row)
    row.schedule_card_id = card.id
    row.surgeon_id = card.surgeon_id
    row.location_id = location_id or card.effective_location_id
    row.activity_date = card.date
    row.session = card.session
    row.activity_type = activity_type
    row.start_time = start_time
    row.end_time = end_time
    row.patient_name = (patient_name or "Patient").strip()
    row.procedure = procedure or ""
    row.room_text = (room_text or "").strip() or None
    row.identity_key = _identity(row.patient_name, start_time, activity_type)
    row.is_active = is_active
    row.fax_ingest_row_id = fax_ingest_row_id
    row.aprima_appointment_id = aprima_appointment_id
    if or_block_instance_id is not _LEAVE_BLOCK:
        row.or_block_instance_id = or_block_instance_id
    return row


def resolve_schedule_card(
    db: Session,
    *,
    surgeon_id: int | None,
    day: date | None,
    location_id: int | None,
    start_time: time | None,
    preferred_session: str | None = None,
) -> ScheduleCard | None:
    if not surgeon_id or not day:
        return None
    cards = db.query(ScheduleCard).filter(
        ScheduleCard.surgeon_id == surgeon_id,
        ScheduleCard.date == day,
    ).all()
    if not cards:
        return None
    location_matches = [row for row in cards if location_id and row.effective_location_id == location_id]
    candidates = location_matches or cards
    if len(candidates) == 1:
        return candidates[0]
    session = (preferred_session or "").lower()
    if session not in {"am", "pm"}:
        session = "pm" if start_time and start_time >= time(12, 0) else "am"
    return next((row for row in candidates if row.session == session), None)


def _meeting_title(payload: dict) -> str:
    raw = (payload.get("reason") or payload.get("appointmentType") or "Meeting").strip()
    title = re.sub(r"(?i)^meeting\s*[-:]?\s*", "", raw).strip() or "Meeting"
    return title[:255]


def _upsert_aprima_meeting(
    db: Session,
    payload: dict,
    *,
    day: date,
    surgeon: Surgeon | None,
    start_time: time | None,
    end_time: time | None,
) -> None:
    from .admin_meeting_service import sync_meeting_attendees

    key = str(payload.get("id") or "").strip()
    if not key:
        return
    meeting = db.query(Meeting).filter(
        Meeting.source_system == "aprima",
        Meeting.source_record_key == key,
    ).one_or_none()
    if meeting is None:
        meeting = Meeting(source_system="aprima", source_record_key=key, title=_meeting_title(payload), date=day)
        db.add(meeting)
        db.flush()
    meeting.title = _meeting_title(payload)
    meeting.date = day
    meeting.start_time = start_time
    meeting.end_time = end_time
    meeting.location_text = ((payload.get("serviceSite") or payload.get("room") or "").strip() or None)
    meeting.notes = (payload.get("reason") or "").strip() or None
    sync_meeting_attendees(db, meeting, [surgeon.id] if surgeon else [])


def normalize_aprima_payload(
    db: Session,
    payload: dict,
    *,
    kind: str,
) -> None:
    from .aprima_schedule_service import (
        appointment_belongs_to_surgeon,
        is_surgery_appointment,
        resolve_aprima_facility_name,
    )

    appointment_id = str(payload.get("id") or "").strip()
    if not appointment_id:
        return
    try:
        day = date.fromisoformat(str(payload.get("date") or ""))
    except ValueError:
        return
    clock = _clock(payload.get("start"))
    surgeons = db.query(Surgeon).filter(Surgeon.is_active == True).all()  # noqa: E712
    surgeon = next((row for row in surgeons if appointment_belongs_to_surgeon(payload, row)), None)
    is_meeting = kind == "meeting"
    is_surgery = bool(not is_meeting and is_surgery_appointment(payload))
    facility = resolve_aprima_facility_name(
        payload.get("serviceSite") or "",
        is_surgery=is_surgery,
    ) if not is_meeting else ""
    locations = db.query(Location).filter(Location.is_active == True).all()  # noqa: E712
    location_map = {
        _key(label): row
        for row in locations
        for label in (row.name, row.abbreviation)
        if label
    }
    cbo = next((row for row in locations if (row.abbreviation or "").upper() == "CBO-OV"), None)
    if cbo:
        location_map[_key("Surgery One")] = cbo
        location_map[_key("Clermont Business Office")] = cbo
    location = location_map.get(_key(facility)) or location_map.get(_key(payload.get("serviceSite")))
    session = "pm" if clock and clock >= time(12, 0) else "am"
    end_time = _clock(payload.get("end"))
    if is_meeting:
        _upsert_aprima_meeting(
            db,
            payload,
            day=day,
            surgeon=surgeon,
            start_time=clock,
            end_time=end_time,
        )
        db.query(ScheduleCardActivity).filter(
            ScheduleCardActivity.source_system == "aprima",
            ScheduleCardActivity.source_record_key == appointment_id,
        ).update({ScheduleCardActivity.is_active: False}, synchronize_session=False)
        return
    card = resolve_schedule_card(
        db,
        surgeon_id=surgeon.id if surgeon else None,
        day=day,
        location_id=location.id if location else None,
        start_time=clock,
        preferred_session=session,
    )
    room_text = (payload.get("room") or payload.get("serviceSite") or "").strip() or None
    patient_name = (payload.get("patientName") or "").strip() or None
    if card:
        _upsert_activity(
            db,
            source_system="aprima",
            source_record_key=appointment_id,
            card=card,
            activity_type="surgical" if is_surgery else "clinic",
            start_time=clock,
            end_time=end_time,
            patient_name=patient_name or "Patient",
            procedure=(payload.get("appointmentType") or payload.get("procedure") or "").strip(),
            room_text=room_text,
            location_id=location.id if location else None,
            aprima_appointment_id=appointment_id[:36],
        )
    else:
        db.query(ScheduleCardActivity).filter(
            ScheduleCardActivity.source_system == "aprima",
            ScheduleCardActivity.source_record_key == appointment_id,
        ).update({ScheduleCardActivity.is_active: False}, synchronize_session=False)


def sync_applied_fax_clinic_activities(db: Session, run: FaxIngestRun) -> int:
    rows = (
        db.query(FaxIngestRow, FaxRowDecision, ScheduleCard)
        .join(FaxRowDecision, FaxRowDecision.fax_row_id == FaxIngestRow.id)
        .join(ScheduleCard, ScheduleCard.id == FaxRowDecision.schedule_card_id)
        .filter(FaxIngestRow.run_id == run.id, FaxIngestRow.row_type == "clinic")
        .all()
    )
    applicable_ids = {
        row_id
        for (row_id,) in db.execute(
            text("SELECT fax_row_id FROM fax_ingest_rows_applicable WHERE run_id = :run_id"),
            {"run_id": run.id},
        )
    }
    rows = [item for item in rows if item[0].id in applicable_ids]
    if not rows:
        return 0
    surgeon_ids = {row.surgeon_id for row, _, _ in rows if row.surgeon_id}
    days = {row.case_date for row, _, _ in rows}
    db.query(ScheduleCardActivity).filter(
        ScheduleCardActivity.source_system == "fax_clinic",
        ScheduleCardActivity.surgeon_id.in_(surgeon_ids),
        ScheduleCardActivity.activity_date.in_(days),
    ).update({ScheduleCardActivity.is_active: False}, synchronize_session=False)
    for fax_row, _, card in rows:
        _upsert_activity(
            db,
            source_system="fax_clinic",
            source_record_key=f"{run.id}:{fax_row.id}",
            card=card,
            activity_type="clinic",
            start_time=fax_row.start_time,
            patient_name=fax_row.patient_name,
            procedure=fax_row.procedure,
            room_text=fax_row.room_text,
            location_id=fax_row.source_location_id or card.effective_location_id,
            fax_ingest_row_id=fax_row.id,
        )
    return len(rows)


def reconcile_applied_fax_versions(db: Session) -> int:
    """Make only the newest applied fax rows for each date active; past dates stay as they were.

    When the scratch reading is already gone, the card line is the schedule.
    An empty reading must not turn those lines off.
    """
    db.flush()
    today = datetime.now(ZoneInfo(PRACTICE_TIMEZONE)).date()
    ranked = (
        db.query(
            FaxIngestRow.id.label("row_id"),
            func.dense_rank().over(
                partition_by=FaxIngestRow.case_date,
                order_by=(FaxDocument.external_fax_id.desc(), FaxIngestRun.id.desc()),
            ).label("revision_rank"),
        )
        .join(FaxIngestRun, FaxIngestRun.id == FaxIngestRow.run_id)
        .join(FaxDocument, FaxDocument.id == FaxIngestRun.fax_document_id)
        .filter(
            FaxIngestRun.status == "applied",
            FaxIngestRow.row_type == "clinic",
            FaxIngestRow.case_date >= today,
        )
        .subquery()
    )
    newest_ids = [row_id for (row_id,) in db.query(ranked.c.row_id).filter(ranked.c.revision_rank == 1).all()]
    if not newest_ids:
        return 0
    db.query(ScheduleCardActivity).filter(
        ScheduleCardActivity.source_system == "fax_clinic",
        ScheduleCardActivity.activity_date >= today,
    ).update({ScheduleCardActivity.is_active: False}, synchronize_session=False)
    updated = db.query(ScheduleCardActivity).filter(
        ScheduleCardActivity.fax_ingest_row_id.in_(newest_ids),
    ).update({ScheduleCardActivity.is_active: True}, synchronize_session=False)
    db.expire_all()
    return updated


def backfill_normalized_schedule_activity(db: Session) -> dict[str, int]:
    surgical = 0
    missing = db.query(ScheduleCardActivity).filter(
        ScheduleCardActivity.source_system == "aprima",
        ScheduleCardActivity.aprima_appointment_id.is_(None),
    ).all()
    for activity in missing:
        activity.aprima_appointment_id = (activity.source_record_key or "")[:36] or None
    aprima = len(missing)
    fax = 0
    applied_runs = (
        db.query(FaxIngestRun)
        .join(FaxDocument, FaxDocument.id == FaxIngestRun.fax_document_id)
        .filter(FaxIngestRun.status == "applied")
        .order_by(FaxDocument.external_fax_id, FaxIngestRun.id)
        .all()
    )
    for run in applied_runs:
        fax += sync_applied_fax_clinic_activities(db, run)
    reconcile_applied_fax_versions(db)
    db.commit()
    return {"surgical": surgical, "aprima": aprima, "fax": fax}
