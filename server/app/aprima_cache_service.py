"""Pull Aprima meetings and Surgery One patients onto the real tables.

Aprima stays read-only. Meetings land on the meetings list. A Surgery One
patient lands on that surgeon's card when the card exists. The scratch list is gone.
"""
from __future__ import annotations

import hashlib
import logging
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
from .models import AprimaSyncState, Meeting, ScheduleCardActivity, Surgeon
from .push import send_native_push_to_surgeon
from .scheduling_gate_service import practice_today
from .surgeon_visibility import surgeon_is_visible

log = logging.getLogger(__name__)

CACHE_KIND_PATIENT = "patient"
CACHE_KIND_MEETING = "meeting"
DEFAULT_SYNC_DAYS_AHEAD = 21
# Prefer cache if last successful sync is newer than this.
CACHE_MAX_AGE = timedelta(hours=2)
# Manual/hourly overlap: treat a sync as in-flight only this long, then allow retry.
SYNC_RUNNING_MAX_AGE = timedelta(minutes=15)


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
        "running": aprima_sync_is_running(db, state=state),
    }


def aprima_sync_is_running(db: Session, *, state: AprimaSyncState | None = None) -> bool:
    """True when a pull is in flight and not stale (stuck)."""
    row = state or get_sync_state(db)
    if (row.last_status or "") != "running" or not row.last_started_at:
        return False
    return (_utc_now() - row.last_started_at) <= SYNC_RUNNING_MAX_AGE


def begin_manual_aprima_sync(db: Session) -> dict:
    """Mark a manual pull started, or report that one is already running. No PHI."""
    if aprima_sync_is_running(db):
        return {
            "ok": True,
            "started": False,
            "alreadyRunning": True,
            "status": sync_status_payload(db),
        }
    state = get_sync_state(db)
    state.last_started_at = _utc_now()
    state.last_status = "running"
    state.last_error = None
    db.commit()
    return {
        "ok": True,
        "started": True,
        "alreadyRunning": False,
        "status": sync_status_payload(db),
    }


def run_aprima_sync_job(*, notify: bool = True) -> dict:
    """Own a DB session for a background / cron-style pull. Never writes to Aprima."""
    from .database import SessionLocal

    db = SessionLocal()
    try:
        return run_aprima_sync(db, notify=notify)
    except Exception:
        log.exception("Aprima sync job failed")
        raise
    finally:
        db.close()


def cache_is_usable(db: Session) -> bool:
    state = get_sync_state(db)
    if state.last_status != "ok" or not state.last_finished_at:
        return False
    return (_utc_now() - state.last_finished_at) <= CACHE_MAX_AGE


def _aprima_line_fingerprint(db: Session, initials: str, start_date: date, end_date: date) -> str:
    key = (initials or "").strip().upper()
    rows = (
        db.query(ScheduleCardActivity)
        .join(Surgeon, Surgeon.id == ScheduleCardActivity.surgeon_id)
        .filter(
            ScheduleCardActivity.source_system == "aprima",
            ScheduleCardActivity.is_active == True,  # noqa: E712
            ScheduleCardActivity.activity_date >= start_date,
            ScheduleCardActivity.activity_date <= end_date,
        )
        .all()
    )
    mine = []
    for line in rows:
        if (line.surgeon.initials or "").strip().upper() != key:
            continue
        mine.append({
            "id": line.source_record_key,
            "date": line.activity_date.isoformat() if line.activity_date else "",
            "start": line.start_time.strftime("%H:%M") if line.start_time else "",
            "end": line.end_time.strftime("%H:%M") if line.end_time else "",
            "patientName": line.patient_name or "",
            "appointmentType": line.procedure or "",
            "room": line.room_text or "",
        })
    return fingerprint_rows(mine)


def patient_appointments_for_api(
    db: Session,
    start_date: date,
    end_date: date,
    surgeon: Surgeon | None = None,
) -> dict:
    """Native Patients tab reads Aprima live. Saved card lines stay the schedule."""
    warning = None
    source = "live"
    state = get_sync_state(db)
    synced_at = state.last_finished_at.isoformat() if state.last_finished_at else None
    try:
        rows = fetch_patient_appointments(start_date, end_date)
    except AprimaScheduleUnavailable as exc:
        rows = []
        warning = str(exc)
    except Exception as exc:  # noqa: BLE001
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
    """Dashboard Surgery One week from the live Aprima pull."""
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
            "isToday": day == practice_today(),
        })

    today = practice_today()
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
    """Admin Meetings page reads Aprima rows saved on the meetings list."""
    state = get_sync_state(db)
    saved = (
        db.query(Meeting)
        .filter(
            Meeting.source_system == "aprima",
            Meeting.date >= start_date,
            Meeting.date <= end_date,
        )
        .order_by(Meeting.date, Meeting.start_time, Meeting.id)
        .all()
    )
    meetings = []
    for meeting in saved:
        attendee = next((row for row in (meeting.attendees or []) if row.surgeon), None)
        surgeon = attendee.surgeon if attendee else None
        day_text = meeting.date.isoformat() if meeting.date else ""
        try:
            display_date = meeting.date.strftime("%a, %b %-d") if meeting.date else ""
        except ValueError:
            display_date = day_text
        meetings.append({
            "id": meeting.source_record_key or str(meeting.id),
            "date": day_text,
            "start": meeting.start_time.strftime("%H:%M") if meeting.start_time else "",
            "end": meeting.end_time.strftime("%H:%M") if meeting.end_time else "",
            "title": meeting.title or "Meeting",
            "displayDate": display_date,
            "source": "aprima",
            "surgeonInitials": surgeon.initials if surgeon else "",
            "surgeonName": surgeon.full_name if surgeon else "",
            "serviceSite": meeting.location_text or "",
            "room": "",
            "reason": meeting.notes or "",
            "patientName": "",
            "appointmentType": "",
        })
    return {
        "range": {"start": start_date.isoformat(), "end": end_date.isoformat()},
        "meetings": meetings,
        "warning": None,
        "source": "schedule",
        "syncedAt": state.last_finished_at.isoformat() if state.last_finished_at else None,
        "fingerprint": state.content_fingerprint or "",
    }


def run_aprima_sync(
    db: Session,
    *,
    days_ahead: int = DEFAULT_SYNC_DAYS_AHEAD,
    notify: bool = True,
) -> dict:
    """Pull Aprima onto meetings and card lines. Never writes to Aprima."""
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
        previous_patient_fp[initials] = _aprima_line_fingerprint(
            db, initials, window_start, window_end
        )

    now = _utc_now()
    seen_patients: set[str] = set()
    seen_meetings: set[str] = set()

    def upsert(kind: str, rows: list[dict], seen: set[str]) -> None:
        from .schedule_activity_normalization import normalize_aprima_payload

        for row in rows:
            appt_id = str(row.get("id") or "").strip()
            if not appt_id:
                continue
            try:
                date.fromisoformat(row.get("date") or "")
            except ValueError:
                continue
            seen.add(appt_id)
            normalize_aprima_payload(db, row, kind=kind)

    upsert(CACHE_KIND_PATIENT, patients, seen_patients)
    upsert(CACHE_KIND_MEETING, meeting_rows, seen_meetings)
    # Flush moves before the SQL delete so a meeting that changed date is not removed.
    db.flush()

    quiet_lines = db.query(ScheduleCardActivity).filter(
        ScheduleCardActivity.source_system == "aprima",
        ScheduleCardActivity.activity_date >= window_start,
        ScheduleCardActivity.activity_date <= window_end,
    )
    if seen_patients:
        quiet_lines = quiet_lines.filter(
            ~ScheduleCardActivity.source_record_key.in_(list(seen_patients))
        )
    quiet_lines.update({ScheduleCardActivity.is_active: False}, synchronize_session=False)

    quiet_meetings = db.query(Meeting).filter(
        Meeting.source_system == "aprima",
        Meeting.date >= window_start,
        Meeting.date <= window_end,
    )
    if seen_meetings:
        quiet_meetings = quiet_meetings.filter(
            ~Meeting.source_record_key.in_(list(seen_meetings))
        )
    quiet_meetings.delete(synchronize_session=False)
    outside_meetings = db.query(Meeting).filter(
        Meeting.source_system == "aprima",
        (Meeting.date < window_start) | (Meeting.date > window_end),
    )
    if seen_meetings:
        outside_meetings = outside_meetings.filter(
            ~Meeting.source_record_key.in_(list(seen_meetings))
        )
    outside_meetings.delete(synchronize_session=False)
    db.flush()

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
            new_fp = _aprima_line_fingerprint(db, initials, window_start, window_end)
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
