"""CAL-side cache for Aprima patient appointments and meetings.

Aprima remains read-only. The hourly worker writes here; portal + native APIs
prefer cache when fresh, with live Aprima fallback.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
from datetime import date, datetime, timedelta, timezone

from sqlalchemy.orm import Session

from .aprima_schedule_service import (
    AprimaScheduleUnavailable,
    appointment_belongs_to_surgeon,
    fetch_aprima_meetings,
    fetch_patient_appointments,
    is_surgical_one_dashboard_appointment,
    main_office_site_tokens,
    weekday_range,
)
from .models import AprimaCachedAppointment, AprimaSyncState, Surgeon
from .push import send_native_push_to_surgeon
from .scheduling_gate_service import practice_today
from .surgeon_visibility import surgeon_is_visible

log = logging.getLogger(__name__)

CACHE_KIND_PATIENT = "patient"
CACHE_KIND_MEETING = "meeting"
DEFAULT_SYNC_DAYS_AHEAD = 21
# Prefer cache if last successful sync is newer than this.
CACHE_MAX_AGE = timedelta(hours=2)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def sync_window(days_ahead: int = DEFAULT_SYNC_DAYS_AHEAD) -> tuple[date, date]:
    start = practice_today()
    return start, start + timedelta(days=max(1, days_ahead))


def row_content_hash(row: dict) -> str:
    """Stable hash of schedule-relevant fields (used for change detection)."""
    parts = [
        str(row.get("id") or ""),
        str(row.get("date") or ""),
        str(row.get("start") or ""),
        str(row.get("end") or ""),
        str(row.get("status") or ""),
        str(row.get("serviceSite") or ""),
        str(row.get("room") or ""),
        str(row.get("appointmentType") or ""),
        str(row.get("reason") or ""),
        str(row.get("surgeonInitials") or ""),
        str(row.get("patientName") or ""),
        str(row.get("mrn") or ""),
    ]
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


def fingerprint_rows(rows: list[dict]) -> str:
    digests = sorted(row_content_hash(row) for row in rows)
    return hashlib.sha256("\n".join(digests).encode("utf-8")).hexdigest()


def get_sync_state(db: Session) -> AprimaSyncState:
    state = db.query(AprimaSyncState).order_by(AprimaSyncState.id.asc()).first()
    if state:
        return state
    state = AprimaSyncState(last_status="never")
    db.add(state)
    db.commit()
    db.refresh(state)
    return state


def sync_status_payload(db: Session) -> dict:
    state = get_sync_state(db)
    age_seconds = None
    if state.last_finished_at:
        age_seconds = max(0, int((_utc_now() - state.last_finished_at).total_seconds()))
    return {
        "status": state.last_status or "never",
        "lastStartedAt": state.last_started_at.isoformat() if state.last_started_at else None,
        "lastFinishedAt": state.last_finished_at.isoformat() if state.last_finished_at else None,
        "ageSeconds": age_seconds,
        "patientCount": state.patient_count or 0,
        "meetingCount": state.meeting_count or 0,
        "windowStart": state.window_start.isoformat() if state.window_start else None,
        "windowEnd": state.window_end.isoformat() if state.window_end else None,
        "fingerprint": state.content_fingerprint or "",
        "error": state.last_error or None,
        "cacheFresh": bool(
            state.last_status == "ok"
            and state.last_finished_at
            and (_utc_now() - state.last_finished_at) <= CACHE_MAX_AGE
        ),
    }


def _serialize_cached(row: AprimaCachedAppointment) -> dict:
    try:
        payload = json.loads(row.payload_json)
    except (TypeError, ValueError):
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    payload.setdefault("id", row.appointment_id)
    payload.setdefault("date", row.date.isoformat() if row.date else "")
    payload.setdefault("surgeonInitials", row.surgeon_initials or "")
    return payload


def cache_is_usable(db: Session) -> bool:
    state = get_sync_state(db)
    if state.last_status != "ok" or not state.last_finished_at:
        return False
    return (_utc_now() - state.last_finished_at) <= CACHE_MAX_AGE


def cached_patient_appointments(db: Session, start_date: date, end_date: date) -> list[dict]:
    rows = (
        db.query(AprimaCachedAppointment)
        .filter(
            AprimaCachedAppointment.kind == CACHE_KIND_PATIENT,
            AprimaCachedAppointment.date >= start_date,
            AprimaCachedAppointment.date <= end_date,
        )
        .order_by(AprimaCachedAppointment.date, AprimaCachedAppointment.appointment_id)
        .all()
    )
    return [_serialize_cached(row) for row in rows]


def cached_meetings(db: Session, start_date: date, end_date: date) -> list[dict]:
    rows = (
        db.query(AprimaCachedAppointment)
        .filter(
            AprimaCachedAppointment.kind == CACHE_KIND_MEETING,
            AprimaCachedAppointment.date >= start_date,
            AprimaCachedAppointment.date <= end_date,
        )
        .order_by(AprimaCachedAppointment.date, AprimaCachedAppointment.appointment_id)
        .all()
    )
    out = []
    for row in rows:
        payload = _serialize_cached(row)
        title = payload.get("reason") or payload.get("appointmentType") or "Meeting"
        title = re.sub(r"(?i)^meeting\s*[-:]?\s*", "", title).strip() or "Meeting"
        display_date = payload.get("date") or ""
        try:
            display_date = date.fromisoformat(display_date).strftime("%a, %b %-d")
        except ValueError:
            pass
        out.append({
            **payload,
            "title": title,
            "displayDate": display_date,
            "source": "aprima",
        })
    return out


def patient_appointments_for_api(
    db: Session,
    start_date: date,
    end_date: date,
    surgeon: Surgeon | None = None,
) -> dict:
    """Native Patients tab: cache-first, live Aprima fallback."""
    warning = None
    source = "cache"
    synced_at = None
    state = get_sync_state(db)
    if cache_is_usable(db):
        rows = cached_patient_appointments(db, start_date, end_date)
        synced_at = state.last_finished_at.isoformat() if state.last_finished_at else None
    else:
        source = "live"
        try:
            rows = fetch_patient_appointments(start_date, end_date)
        except AprimaScheduleUnavailable as exc:
            stale = cached_patient_appointments(db, start_date, end_date)
            if stale:
                rows = stale
                source = "cache_stale"
                warning = f"Showing last Aprima sync (live unavailable): {exc}"
                synced_at = state.last_finished_at.isoformat() if state.last_finished_at else None
            else:
                rows = []
                warning = str(exc)
        except Exception as exc:  # noqa: BLE001
            stale = cached_patient_appointments(db, start_date, end_date)
            if stale:
                rows = stale
                source = "cache_stale"
                warning = f"Showing last Aprima sync (live unavailable): {exc}"
                synced_at = state.last_finished_at.isoformat() if state.last_finished_at else None
            else:
                rows = []
                warning = f"Aprima temporarily unavailable: {exc}"

    if surgeon is not None:
        rows = [row for row in rows if appointment_belongs_to_surgeon(row, surgeon)]
    return {
        "range": {"start": start_date.isoformat(), "end": end_date.isoformat()},
        "appointments": rows,
        "warning": warning,
        "source": source,
        "syncedAt": synced_at,
        "fingerprint": state.content_fingerprint or "",
    }


def main_office_patients_by_weekday(db: Session, anchor: date | None = None) -> dict:
    """Dashboard Surgery One week — cache-first, any clinic/hospital site."""
    week_start, week_end = weekday_range(anchor)
    tokens = main_office_site_tokens()
    payload = patient_appointments_for_api(db, week_start, week_end, surgeon=None)
    rows = [
        row
        for row in (payload.get("appointments") or [])
        if is_surgical_one_dashboard_appointment(row, office_tokens=tokens)
    ]
    warning = payload.get("warning")

    days = []
    for offset in range(5):
        day = week_start + timedelta(days=offset)
        day_key = day.isoformat()
        day_rows = [row for row in rows if row.get("date") == day_key]
        clinics: list[str] = []
        surgeons: list[str] = []
        for row in day_rows:
            site = (row.get("serviceSite") or "").strip()
            if site and site not in clinics:
                clinics.append(site)
            initials = (row.get("surgeonInitials") or "").strip()
            if not initials:
                name = (row.get("surgeonName") or "").strip()
                initials = "".join(part[:1] for part in name.split() if part)[:3]
            if initials and initials not in surgeons:
                surgeons.append(initials)
        days.append({
            "date": day,
            "dateKey": day_key,
            "weekday": day.strftime("%a"),
            "label": day.strftime("%a %-d"),
            "count": len(day_rows),
            "appointments": day_rows,
            "clinics": clinics,
            "surgeons": surgeons,
            "clinicLabel": ", ".join(clinics),
            "surgeonLabel": ", ".join(surgeons),
            "isToday": day == date.today(),
        })

    today = date.today()
    return {
        "weekStart": week_start,
        "weekEnd": week_end,
        "prevWeek": week_start - timedelta(days=7),
        "nextWeek": week_start + timedelta(days=7),
        "isCurrentWeek": week_start == weekday_range(today)[0],
        "siteTokens": tokens,
        "days": days,
        "total": len(rows),
        "warning": warning,
        "source": payload.get("source"),
        "syncedAt": payload.get("syncedAt"),
        "fingerprint": get_sync_state(db).content_fingerprint or "",
    }


def meetings_for_admin(db: Session, start_date: date, end_date: date) -> dict:
    """Admin Meetings page Aprima merge — cache-first."""
    state = get_sync_state(db)
    if cache_is_usable(db):
        meetings = cached_meetings(db, start_date, end_date)
        return {
            "range": {"start": start_date.isoformat(), "end": end_date.isoformat()},
            "meetings": meetings,
            "warning": None,
            "source": "cache",
            "syncedAt": state.last_finished_at.isoformat() if state.last_finished_at else None,
            "fingerprint": state.content_fingerprint or "",
        }
    live = fetch_aprima_meetings(start_date, end_date)
    if live.get("warning") and not (live.get("meetings") or []):
        stale = cached_meetings(db, start_date, end_date)
        if stale:
            return {
                "range": {"start": start_date.isoformat(), "end": end_date.isoformat()},
                "meetings": stale,
                "warning": f"Showing last Aprima sync (live unavailable): {live.get('warning')}",
                "source": "cache_stale",
                "syncedAt": state.last_finished_at.isoformat() if state.last_finished_at else None,
                "fingerprint": state.content_fingerprint or "",
            }
    return {
        **live,
        "source": "live",
        "syncedAt": None,
        "fingerprint": state.content_fingerprint or "",
    }


def _surgeon_fingerprint(rows: list[dict], initials: str) -> str:
    key = (initials or "").strip().upper()
    mine = [
        row for row in rows
        if (row.get("surgeonInitials") or "").strip().upper() == key
    ]
    return fingerprint_rows(mine)


def run_aprima_sync(
    db: Session,
    *,
    days_ahead: int = DEFAULT_SYNC_DAYS_AHEAD,
    notify: bool = True,
) -> dict:
    """Pull Aprima into CAL cache. Never writes to Aprima."""
    state = get_sync_state(db)
    prior_fingerprint = state.content_fingerprint or ""
    started = _utc_now()
    state.last_started_at = started
    state.last_status = "running"
    state.last_error = None
    db.commit()

    window_start, window_end = sync_window(days_ahead)
    try:
        patients = fetch_patient_appointments(window_start, window_end)
        meetings_raw = fetch_aprima_meetings(window_start, window_end)
        if meetings_raw.get("warning") and not meetings_raw.get("meetings"):
            raise AprimaScheduleUnavailable(str(meetings_raw["warning"]))
        meetings = list(meetings_raw.get("meetings") or [])
        meeting_rows = []
        for row in meetings:
            meeting_rows.append({
                "id": row.get("id"),
                "date": row.get("date"),
                "start": row.get("start"),
                "end": row.get("end"),
                "timeZone": row.get("timeZone") or "America/New_York",
                "surgeonInitials": row.get("surgeonInitials") or "",
                "surgeonName": row.get("surgeonName") or "",
                "patientName": row.get("patientName") or "",
                "mrn": "",
                "appointmentType": row.get("appointmentType") or "",
                "status": row.get("status") or "",
                "reason": row.get("reason") or "",
                "serviceSite": row.get("serviceSite") or "",
                "room": row.get("room") or "",
            })
    except Exception as exc:  # noqa: BLE001
        state.last_finished_at = _utc_now()
        state.last_status = "error"
        state.last_error = str(exc)[:1000]
        db.commit()
        log.warning("Aprima sync failed: %s", type(exc).__name__)
        return {"ok": False, "error": str(exc), "status": sync_status_payload(db)}

    previous_patient_fp: dict[str, str] = {}
    for surgeon in db.query(Surgeon).filter(Surgeon.is_active == True).all():  # noqa: E712
        if not surgeon_is_visible(surgeon):
            continue
        initials = (surgeon.initials or "").strip().upper()
        if not initials:
            continue
        existing = cached_patient_appointments(db, window_start, window_end)
        previous_patient_fp[initials] = _surgeon_fingerprint(existing, initials)

    now = _utc_now()
    seen_ids: set[str] = set()

    def upsert(kind: str, rows: list[dict]) -> None:
        for row in rows:
            appt_id = str(row.get("id") or "").strip()
            if not appt_id:
                continue
            day_text = row.get("date") or ""
            try:
                day = date.fromisoformat(day_text)
            except ValueError:
                continue
            seen_ids.add(appt_id)
            digest = row_content_hash(row)
            existing = db.get(AprimaCachedAppointment, appt_id)
            payload = json.dumps(row, separators=(",", ":"), sort_keys=True)
            if existing:
                existing.kind = kind
                existing.date = day
                existing.surgeon_initials = (row.get("surgeonInitials") or "")[:16]
                existing.content_hash = digest
                existing.payload_json = payload
                existing.synced_at = now
            else:
                db.add(AprimaCachedAppointment(
                    appointment_id=appt_id,
                    kind=kind,
                    date=day,
                    surgeon_initials=(row.get("surgeonInitials") or "")[:16],
                    content_hash=digest,
                    payload_json=payload,
                    synced_at=now,
                ))

    upsert(CACHE_KIND_PATIENT, patients)
    upsert(CACHE_KIND_MEETING, meeting_rows)
    # Flush date moves before out-of-window SQL delete. Otherwise synchronize_session=False
    # deletes the old DB row while the session still holds a dirty UPDATE → StaleDataError.
    db.flush()

    window_rows = (
        db.query(AprimaCachedAppointment)
        .filter(
            AprimaCachedAppointment.date >= window_start,
            AprimaCachedAppointment.date <= window_end,
        )
        .all()
    )
    for row in window_rows:
        if row.appointment_id not in seen_ids:
            db.delete(row)

    stale_outside = db.query(AprimaCachedAppointment).filter(
        (AprimaCachedAppointment.date < window_start) | (AprimaCachedAppointment.date > window_end)
    )
    if seen_ids:
        stale_outside = stale_outside.filter(
            ~AprimaCachedAppointment.appointment_id.in_(list(seen_ids))
        )
    stale_outside.delete(synchronize_session=False)

    all_fp = fingerprint_rows(patients + meeting_rows)
    state.last_finished_at = now
    state.last_status = "ok"
    state.last_error = None
    state.patient_count = len(patients)
    state.meeting_count = len(meeting_rows)
    state.window_start = window_start
    state.window_end = window_end
    state.content_fingerprint = all_fp
    db.commit()

    changed_surgeons: list[str] = []
    # Only push after a prior successful sync so the first seed does not spam devices.
    if notify and prior_fingerprint:
        for surgeon in db.query(Surgeon).filter(Surgeon.is_active == True).all():  # noqa: E712
            if not surgeon_is_visible(surgeon):
                continue
            initials = (surgeon.initials or "").strip().upper()
            if not initials:
                continue
            new_fp = _surgeon_fingerprint(patients, initials)
            old_fp = previous_patient_fp.get(initials, "")
            if new_fp != old_fp:
                changed_surgeons.append(initials)
                send_native_push_to_surgeon(
                    surgeon.id,
                    "Clinic schedule updated",
                    "Your Surgical One / Aprima patients changed. Open Patients to refresh.",
                    db,
                    {"kind": "aprima_patients", "type": "aprima_sync"},
                )

    log.info(
        "Aprima sync ok patients=%s meetings=%s changed_surgeons=%s",
        len(patients),
        len(meeting_rows),
        len(changed_surgeons),
    )
    return {
        "ok": True,
        "patients": len(patients),
        "meetings": len(meeting_rows),
        "changedSurgeons": len(changed_surgeons),
        "status": sync_status_payload(db),
    }
