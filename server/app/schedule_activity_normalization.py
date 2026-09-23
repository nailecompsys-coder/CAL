"""Write transport payloads into normalized schedule columns exactly once."""

from __future__ import annotations

import json
import re
from datetime import date, time

from sqlalchemy import func
from sqlalchemy.orm import Session

from .models import (
    AprimaCachedAppointment,
    FaxDocument,
    FaxIngestRow,
    FaxIngestRun,
    FaxRowDecision,
    Location,
    ScheduleCard,
    ScheduleCardActivity,
    Surgeon,
    SurgicalCase,
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
    surgical_case_id: int | None = None,
    fax_ingest_row_id: int | None = None,
    aprima_appointment_id: str | None = None,
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
    row.surgical_case_id = surgical_case_id
    row.fax_ingest_row_id = fax_ingest_row_id
    row.aprima_appointment_id = aprima_appointment_id
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


def normalize_surgical_case_card(db: Session, case: SurgicalCase) -> ScheduleCard | None:
    if case.id is None:
        db.flush()
    card = resolve_schedule_card(
        db,
        surgeon_id=case.surgeon_id,
        day=case.date,
        location_id=case.location_id,
        start_time=case.start_time,
    )
    case.schedule_card_id = card.id if card else None
    if card:
        _upsert_activity(
            db,
            source_system="surgical_case",
            source_record_key=str(case.id),
            card=card,
            activity_type="surgical",
            start_time=case.start_time,
            end_time=case.end_time,
            patient_name=case.patient_name,
            procedure=case.procedure,
            room_text=case.room_text,
            location_id=case.location_id,
            is_active=(case.status or "scheduled") != "cancelled",
            surgical_case_id=case.id,
        )
    else:
        deactivate_surgical_case_activity(db, case.id)
    return card


def deactivate_surgical_case_activity(db: Session, case_id: int) -> None:
    db.query(ScheduleCardActivity).filter(
        ScheduleCardActivity.source_system == "surgical_case",
        ScheduleCardActivity.source_record_key == str(case_id),
    ).update({ScheduleCardActivity.is_active: False}, synchronize_session=False)


def normalize_aprima_payload(
    db: Session,
    cached: AprimaCachedAppointment,
    payload: dict,
) -> None:
    from .aprima_schedule_service import (
        appointment_belongs_to_surgeon,
        is_surgery_appointment,
        resolve_aprima_facility_name,
    )

    clock = _clock(payload.get("start"))
    surgeons = db.query(Surgeon).filter(Surgeon.is_active == True).all()  # noqa: E712
    surgeon = next((row for row in surgeons if appointment_belongs_to_surgeon(payload, row)), None)
    is_meeting = cached.kind == "meeting"
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
    card = resolve_schedule_card(
        db,
        surgeon_id=surgeon.id if surgeon else None,
        day=cached.date,
        location_id=location.id if location else None,
        start_time=clock,
        preferred_session=session,
    )
    cached.surgeon_id = surgeon.id if surgeon else None
    cached.location_id = location.id if location else None
    cached.schedule_card_id = card.id if card else None
    cached.session = session if not is_meeting else None
    cached.start_time = clock
    cached.end_time = _clock(payload.get("end"))
    cached.patient_name = (payload.get("patientName") or "").strip() or None
    cached.activity_type = "meeting" if is_meeting else ("surgical" if is_surgery else "clinic")
    cached.room_text = (payload.get("room") or payload.get("serviceSite") or "").strip() or None
    cached.service_site = (payload.get("serviceSite") or "").strip() or None
    cached.appointment_type = (payload.get("appointmentType") or "").strip() or None
    cached.reason_text = (payload.get("reason") or "").strip() or None
    if card and not is_meeting:
        _upsert_activity(
            db,
            source_system="aprima",
            source_record_key=cached.appointment_id,
            card=card,
            activity_type="surgical" if is_surgery else "clinic",
            start_time=clock,
            end_time=cached.end_time,
            patient_name=cached.patient_name or "Patient",
            procedure=(payload.get("appointmentType") or payload.get("procedure") or "").strip(),
            room_text=cached.room_text,
            location_id=cached.location_id,
            aprima_appointment_id=cached.appointment_id,
        )
    else:
        db.query(ScheduleCardActivity).filter(
            ScheduleCardActivity.source_system == "aprima",
            ScheduleCardActivity.source_record_key == cached.appointment_id,
        ).update({ScheduleCardActivity.is_active: False}, synchronize_session=False)


def sync_applied_fax_clinic_activities(db: Session, run: FaxIngestRun) -> int:
    rows = (
        db.query(FaxIngestRow, FaxRowDecision, ScheduleCard)
        .join(FaxRowDecision, FaxRowDecision.fax_row_id == FaxIngestRow.id)
        .join(ScheduleCard, ScheduleCard.id == FaxRowDecision.schedule_card_id)
        .filter(FaxIngestRow.run_id == run.id, FaxIngestRow.row_type == "clinic")
        .all()
    )
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
    """Make only the newest applied fax rows for each date active."""
    db.flush()
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
        .filter(FaxIngestRun.status == "applied", FaxIngestRow.row_type == "clinic")
        .subquery()
    )
    newest_ids = [row_id for (row_id,) in db.query(ranked.c.row_id).filter(ranked.c.revision_rank == 1).all()]
    db.query(ScheduleCardActivity).filter(
        ScheduleCardActivity.source_system == "fax_clinic",
    ).update({ScheduleCardActivity.is_active: False}, synchronize_session=False)
    if newest_ids:
        updated = db.query(ScheduleCardActivity).filter(
            ScheduleCardActivity.fax_ingest_row_id.in_(newest_ids),
        ).update({ScheduleCardActivity.is_active: True}, synchronize_session=False)
        db.expire_all()
        return updated
    db.expire_all()
    return 0


def backfill_normalized_schedule_activity(db: Session) -> dict[str, int]:
    surgical = aprima = 0
    for case in db.query(SurgicalCase).all():
        if normalize_surgical_case_card(db, case):
            surgical += 1
    for cached in db.query(AprimaCachedAppointment).filter(
        AprimaCachedAppointment.activity_type.is_(None),
    ).all():
        try:
            payload = json.loads(cached.payload_json or "{}")
        except (TypeError, ValueError):
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        normalize_aprima_payload(db, cached, payload)
        if cached.schedule_card_id or cached.activity_type == "meeting":
            aprima += 1
    for activity in db.query(ScheduleCardActivity).filter(
        ScheduleCardActivity.source_system == "aprima",
        ScheduleCardActivity.aprima_appointment_id.is_(None),
    ).all():
        if db.get(AprimaCachedAppointment, activity.source_record_key):
            activity.aprima_appointment_id = activity.source_record_key
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
