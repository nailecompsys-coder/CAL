"""Single source of truth for Advent fax-to-CAL write rules.

Epic/Advent fax rows are the source for patient schedule facts. CAL overlays
those rows onto existing CAL master cards. Fax ingest may attach or update
case/visit details, but it may not create clinic/OR cards or invent capacity.

Don's big rule (Oct 29, 2026): fax ingest sends NO notifications at all --
no AdminNotification, SMS, email or push. Conflicts are flagged in CAL only.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, time

from sqlalchemy.orm import Session

from .models import DayOff, Location, ORBlockAssignment, ORBlockInstance, ScheduleCard
from .native_dayoff_support import segment_for_date
from .or_block_service import ACTIVE_BLOCK_STATUSES, _host_rank, _session_bucket


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
    card: ScheduleCard | None
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
    """Return the existing OR capacity that can receive a fax case.

    An explicitly materialized ``NA`` session is dated capacity, not a missing
    card. It may use an existing hospital/session capacity row and be converted
    to the fax's actual OR location by the guarded writer. No OR capacity row is
    created here or by fax ingest.
    """
    if not start_time:
        return None
    assigned = (
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
    if assigned:
        return assigned

    session = "am" if start_time < time(12, 0) else "pm"
    na_card = (
        db.query(ScheduleCard)
        .filter(
            ScheduleCard.surgeon_id == surgeon_id,
            ScheduleCard.date == day,
            ScheduleCard.session == session,
            ScheduleCard.effective_state == "na",
        )
        .first()
    )
    if not na_card:
        return None
    return existing_hospital_session_block(
        db,
        block_date=day,
        location_id=location_id,
        start_time=start_time,
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
    sessions = ["am", "pm"] if sess == "full" else [sess]
    cards = (
        db.query(ScheduleCard)
        .filter(
            ScheduleCard.surgeon_id == surgeon_id,
            ScheduleCard.date == day,
            ScheduleCard.session.in_(sessions),
        )
        .order_by(ScheduleCard.id)
        .all()
    )
    if not cards:
        return ClinicCardMatch(None, "clinic_card_not_found")
    if location_id:
        same = [row for row in cards if row.effective_location_id == location_id]
        if same:
            return ClinicCardMatch(same[0], "matched")
    return ClinicCardMatch(cards[0], "matched_session")


def fax_may_update_clinic_location(card: ScheduleCard, loc: Location | None, room: str | None) -> bool:
    """Placeholder rooms are not locations; otherwise a mapped clinic can update."""
    del card
    return loc is not None and not is_placeholder_clinic_room(room)


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
