"""Single source of truth for Advent fax-to-CAL write rules.

Epic/Advent fax rows are the source for patient schedule facts. CAL overlays
those rows onto existing CAL master cards. Fax ingest may attach or update
case/visit details, but it may not create clinic/OR cards or invent capacity.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, time
from html import escape
import json

from sqlalchemy.orm import Session

from .email_service import send_email
from .models import AdminNotification, AdminUser, ClinicSchedule, DayOff, Location, ORBlockAssignment, ORBlockInstance
from .native_dayoff_support import segment_for_date
from .or_block_service import ACTIVE_BLOCK_STATUSES, _host_rank, _session_bucket
from .push import create_admin_notification


PLACEHOLDER_CLINIC_ROOMS = frozenset({"AHMGGENSRG"})

PLACEABLE_REVIEW_REASONS = frozenset({
    "block_not_found",
    "missing_time",
    "missing_block_window",
    "session_card_taken",
    "clinic_card_not_found",
})


@dataclass(frozen=True)
class ClinicCardMatch:
    card: ClinicSchedule | None
    reason: str

    @property
    def ok(self) -> bool:
        return self.card is not None


def normalize_practice_site(raw: str | None) -> str:
    return re.sub(r"[^A-Z0-9]+", "", str(raw or "").upper())


def is_generic_practice_site(raw: str | None) -> bool:
    """AHMGGENSRG/AHMG is a practice bucket, not a physical location."""
    return normalize_practice_site(raw) in {"AHMG", "AHMGGENSRG"}


def is_placeholder_clinic_room(raw: str | None) -> bool:
    return normalize_practice_site(raw) in PLACEHOLDER_CLINIC_ROOMS


def looks_like_surgical_case(slot: dict) -> bool:
    """True only for generic rows that read like OR cases, not clinic visits."""
    text = f"{slot.get('procedure') or ''} {slot.get('visit_type') or ''}".upper()
    clinic_terms = (
        "POST-OP",
        "POST OP",
        "OFFICE VISIT",
        "SPEC OFFICE",
        "GEN SURG NEW",
        "REFERRAL",
        "TELEMEDICINE",
        "US ",
        "ULTRASOUND",
    )
    if any(term in text for term in clinic_terms):
        return False
    surgical_terms = (
        "ROBOTIC",
        "REPAIR",
        "CHOLECYSTECTOMY",
        "EXCISION",
        "PLACEMENT",
        "BIOPSY",
        "COLECTOMY",
        "HERNIA",
        "MASS",
        "CYST",
    )
    return any(term in text for term in surgical_terms)


def matching_assigned_or_block(
    db: Session,
    *,
    surgeon_id: int,
    day: date,
    location_id: int,
    start_time: time | None,
) -> ORBlockInstance | None:
    """Return the existing assigned block that can receive a fax case.

    This is deliberately read-only. If no block exists, the row must be parked
    for review; ingest cannot create a Block OR card.
    """
    if not start_time:
        return None
    return (
        db.query(ORBlockInstance)
        .join(ORBlockAssignment, ORBlockAssignment.block_instance_id == ORBlockInstance.id)
        .filter(
            ORBlockAssignment.surgeon_id == surgeon_id,
            ORBlockInstance.date == day,
            ORBlockInstance.location_id == location_id,
            ORBlockInstance.status.in_(ACTIVE_BLOCK_STATUSES),
            ORBlockInstance.start_time <= start_time,
            ORBlockInstance.end_time > start_time,
        )
        .order_by(ORBlockInstance.start_time, ORBlockInstance.id)
        .first()
    )


def assigned_block_covering_time(
    db: Session,
    *,
    surgeon_id: int,
    day: date,
    at_time: time,
) -> ORBlockInstance | None:
    """Find any existing assigned Block OR row for a generic Advent timed row."""
    rows = (
        db.query(ORBlockInstance)
        .join(ORBlockAssignment, ORBlockAssignment.block_instance_id == ORBlockInstance.id)
        .filter(
            ORBlockAssignment.surgeon_id == surgeon_id,
            ORBlockInstance.date == day,
            ORBlockInstance.status.in_(ACTIVE_BLOCK_STATUSES),
            ORBlockInstance.start_time <= at_time,
            ORBlockInstance.end_time > at_time,
        )
        .order_by(ORBlockInstance.start_time, ORBlockInstance.id)
        .all()
    )
    return rows[0] if rows else None


def existing_hospital_session_block(
    db: Session,
    *,
    block_date: date,
    location_id: int,
    start_time: time,
) -> ORBlockInstance | None:
    """Find the existing hospital AM/PM card for a fax clock.

    Fax rows fit into a master-created card. If no card exists, that is a
    review item, not permission to mint a new card.
    """
    rows = (
        db.query(ORBlockInstance)
        .filter(
            ORBlockInstance.date == block_date,
            ORBlockInstance.location_id == location_id,
            ORBlockInstance.status.in_(ACTIVE_BLOCK_STATUSES),
        )
        .order_by(ORBlockInstance.start_time, ORBlockInstance.id)
        .all()
    )
    if not rows:
        return None
    want = "pm" if start_time >= time(12, 0) else "am"
    containing = [row for row in rows if row.start_time <= start_time < row.end_time]
    same_half = [row for row in rows if _session_bucket(row) == want]
    pool = containing or same_half
    if not pool:
        return None
    return sorted(pool, key=_host_rank)[0]


def existing_clinic_card(
    db: Session,
    *,
    surgeon_id: int,
    day: date,
    session: str,
    location_id: int | None = None,
) -> ClinicCardMatch:
    """Find the existing AM/PM clinic card that a fax visit can update."""
    sess = (session or "pm").lower()
    if sess not in {"am", "pm", "full"}:
        sess = "pm"
    cards = (
        db.query(ClinicSchedule)
        .filter(
            ClinicSchedule.surgeon_id == surgeon_id,
            ClinicSchedule.date == day,
            ClinicSchedule.session.in_([sess, "full"]),
        )
        .order_by(ClinicSchedule.id)
        .all()
    )
    if not cards:
        return ClinicCardMatch(None, "clinic_card_not_found")
    if location_id:
        same = [row for row in cards if row.location_id == location_id]
        if same:
            return ClinicCardMatch(same[0], "matched")
    return ClinicCardMatch(cards[0], "matched_session")


def fax_may_update_clinic_location(card: ClinicSchedule, loc: Location | None, room: str | None) -> bool:
    """Placeholder rooms are not locations; otherwise a mapped clinic can update."""
    del card
    return loc is not None and not is_placeholder_clinic_room(room)


def create_admin_ingest_notice(
    db: Session,
    *,
    title: str,
    body: str,
    kind: str,
    payload: dict | None = None,
    require_schedule_opt_in: bool = False,
) -> None:
    """Admin portal notice only. Fax ingest never uses SMS/email/push."""
    admins = db.query(AdminUser).filter(AdminUser.is_active == True).all()  # noqa: E712
    for admin in admins:
        if require_schedule_opt_in and not admin.notify_schedule_changes:
            continue
        create_admin_notification(admin.id, title, body, db, kind, payload)


def _parse_segment_clock(raw: str | None) -> time | None:
    if not raw:
        return None
    try:
        hour, minute = str(raw).split(":", 1)
        return time(int(hour), int(minute[:2]))
    except (TypeError, ValueError):
        return None


def _time_overlaps_session(start: time | None, end: time | None, session: str | None) -> bool:
    sess = (session or "").lower()
    if not sess or sess in {"full", "both"}:
        return True
    if sess == "am":
        return (start is None or start < time(12, 0)) and (end is None or end > time(0, 0))
    if sess == "pm":
        return end is None or end > time(12, 0)
    return True


def _day_off_covers(day_off: DayOff, day: date, *, at_time: time | None, session: str | None) -> bool:
    segment = segment_for_date(day_off, day) or {}
    if segment.get("isFullDay", day_off.is_full_day if day_off.is_full_day is not None else True):
        return True
    start = _parse_segment_clock(segment.get("start")) or day_off.start_time
    end = _parse_segment_clock(segment.get("end")) or day_off.end_time
    if at_time and start and end:
        return start <= at_time < end
    return _time_overlaps_session(start, end, session)


def approved_day_off_for_ingest(
    db: Session,
    *,
    surgeon_id: int,
    day: date,
    at_time: time | None = None,
    session: str | None = None,
) -> DayOff | None:
    rows = (
        db.query(DayOff)
        .filter(
            DayOff.surgeon_id == surgeon_id,
            DayOff.status == "approved",
            DayOff.start_date <= day,
            DayOff.end_date >= day,
        )
        .order_by(DayOff.id)
        .all()
    )
    for row in rows:
        if _day_off_covers(row, day, at_time=at_time, session=session):
            return row
    return None


def _scheduler_notice_recipients(db: Session) -> list[AdminUser]:
    return (
        db.query(AdminUser)
        .filter(
            AdminUser.is_active == True,  # noqa: E712
            AdminUser.role.in_(("scheduler", "admin", "superadmin")),
            AdminUser.notify_schedule_changes == True,  # noqa: E712
            AdminUser.email.isnot(None),
            AdminUser.email != "",
        )
        .order_by(AdminUser.role.desc(), AdminUser.last_name, AdminUser.first_name, AdminUser.username)
        .all()
    )


def _upsert_admin_day_off_notice(
    db: Session,
    *,
    admin: AdminUser,
    title: str,
    body: str,
    payload: dict,
) -> bool:
    fingerprint = payload.get("fingerprint")
    existing = (
        db.query(AdminNotification)
        .filter(
            AdminNotification.admin_user_id == admin.id,
            AdminNotification.kind == "ingest_day_off_conflict",
        )
        .all()
    )
    for row in existing:
        try:
            data = json.loads(row.payload or "{}") if row.payload else {}
        except (TypeError, ValueError):
            data = {}
        if data.get("fingerprint") != fingerprint:
            continue
        row.title = title
        row.body = body
        row.payload = json.dumps(payload)
        row.read_at = None
        db.commit()
        return False
    create_admin_notification(admin.id, title, body, db, "ingest_day_off_conflict", payload)
    return True


def _send_scheduler_day_off_email(admin: AdminUser, *, title: str, body: str, href: str) -> bool:
    if not admin.email:
        return False
    html = f"""
    <div style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;max-width:680px;color:#0f172a">
      <h2 style="margin:0 0 8px">{escape(title)}</h2>
      <p style="margin:0 0 14px;color:#334155">{escape(body)}</p>
      <p style="margin:0 0 14px;color:#64748b">
        Epic/Advent is the schedule source, so CAL landed the row on the existing card and flagged it for scheduler review.
        No surgeon notification was sent by CAL.
      </p>
      <p><a href="{escape(href)}" style="color:#0369a1;font-weight:700">Open CAL schedule review</a></p>
    </div>
    """
    return bool(send_email(to_email=admin.email, subject=title, html_body=html))


def flag_ingest_day_off_collision(
    db: Session,
    *,
    surgeon_id: int,
    surgeon_name: str,
    day: date,
    source_fax_id: int | None,
    patient_name: str | None,
    landed_kind: str,
    href: str,
    location_label: str | None = None,
    start_time: time | None = None,
    session: str | None = None,
    case_id: int | None = None,
    schedule_id: int | None = None,
) -> bool:
    """Flag Epic fax rows that landed on an approved day off.

    The write still stands because Epic is the external source. The notice is
    scheduler/admin-only and never sends to the surgeon.
    """
    day_off = approved_day_off_for_ingest(
        db,
        surgeon_id=surgeon_id,
        day=day,
        at_time=start_time,
        session=session,
    )
    if not day_off:
        return False
    patient_key = (patient_name or "").strip().lower()
    fingerprint = "|".join(
        [
            "ingest_day_off_conflict",
            str(source_fax_id or ""),
            str(surgeon_id),
            day.isoformat(),
            landed_kind,
            str(case_id or schedule_id or ""),
            patient_key,
            (start_time.strftime("%H:%M") if start_time else session or ""),
        ]
    )
    time_label = start_time.strftime("%H:%M") if start_time else (session or "").upper()
    title = "Fax ingest hit approved OFF"
    body = (
        f"{surgeon_name} · {day.strftime('%m/%d/%Y')}"
        f"{' · ' + time_label if time_label else ''}"
        f"{' · ' + (location_label or '') if location_label else ''}"
        f"{' · ' + (patient_name or '') if patient_name else ''}"
        " landed from Epic/Advent while the surgeon is approved OFF."
    )
    payload = {
        "flagType": "ingest_day_off_conflict",
        "fingerprint": fingerprint,
        "href": href,
        "sourceFaxId": source_fax_id,
        "surgeonId": surgeon_id,
        "surgeonName": surgeon_name,
        "date": day.isoformat(),
        "patientName": patient_name,
        "landedKind": landed_kind,
        "location": location_label,
        "startTime": start_time.strftime("%H:%M") if start_time else None,
        "session": session,
        "caseId": case_id,
        "scheduleId": schedule_id,
        "dayOffId": day_off.id,
        "reason": day_off.reason,
    }
    recipients = _scheduler_notice_recipients(db)
    emailed = False
    created_any = False
    for admin in recipients:
        created = _upsert_admin_day_off_notice(
            db,
            admin=admin,
            title=title,
            body=body,
            payload=payload,
        )
        created_any = created_any or created
        if created:
            emailed = _send_scheduler_day_off_email(admin, title=title, body=body, href=href) or emailed
    return created_any or emailed
