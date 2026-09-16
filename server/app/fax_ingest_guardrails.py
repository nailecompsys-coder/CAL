"""Single source of truth for Advent fax-to-CAL write rules.

Epic/Advent fax rows are the source for patient schedule facts. CAL overlays
those rows onto existing CAL master cards. Fax ingest may attach or update
case/visit details, but it may not create clinic/OR cards or invent capacity.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, time

from sqlalchemy.orm import Session

from .models import AdminUser, ClinicSchedule, Location, ORBlockAssignment, ORBlockInstance
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
