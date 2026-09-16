"""Add-only builder for concrete Clinic / OR cards from the saved master grid."""
from __future__ import annotations

from datetime import date, time, timedelta
import re

from sqlalchemy.orm import Session, joinedload

from .admin_schedule_template_clinic_service import week_pattern_matches
from .admin_schedule_template_common import approved_off_dates
from .ingest_fix_service import save_ingest_placements
from .models import ClinicSchedule, ORBlockAssignment, ORBlockInstance, SurgicalCase, Surgeon, SurgeonLocationSchedule
from .or_block_service import ACTIVE_BLOCK_STATUSES, _session_bucket
from .paper_block_schedule import _place_or_block
from .surgeon_visibility import surgeon_is_visible


def _session_rows(db: Session, surgeon_id: int, day: date) -> dict[str, ClinicSchedule]:
    rows = db.query(ClinicSchedule).filter(
        ClinicSchedule.surgeon_id == surgeon_id,
        ClinicSchedule.date == day,
    ).all()
    result: dict[str, ClinicSchedule] = {}
    for row in rows:
        session = (row.session or "").lower()
        if session in {"am", "pm", "full"}:
            result[session] = row
    return result


def _case_session(case: SurgicalCase) -> str | None:
    if case.start_time is None:
        return None
    return "am" if case.start_time.hour < 12 else "pm"


def _campus(location) -> str:
    return ((getattr(location, "abbreviation", "") or "").split("-", 1)[0]).upper()


def _handoff_sessions(db: Session, case: SurgicalCase) -> list[str]:
    session = _case_session(case)
    if session != "am" or case.start_time is None or case.start_time < time(11, 30):
        return [session] if session else []
    campus = _campus(case.location)
    cards = db.query(ClinicSchedule).filter(
        ClinicSchedule.surgeon_id == case.surgeon_id,
        ClinicSchedule.date == case.date,
        ClinicSchedule.session == "am",
    ).all()
    for card in cards:
        if not card.location or card.location.location_type != "clinic" or _campus(card.location) != campus:
            continue
        times = [time.fromisoformat(value) for value in re.findall(r"\b\d{2}:\d{2}\b", card.notes or "")]
        if times and max(times).hour * 60 + max(times).minute + 30 <= case.start_time.hour * 60 + case.start_time.minute:
            return ["pm", "am"]
    return ["am"]


def reconcile_parked_cases_after_master_build(db: Session, *, start: date, end: date) -> dict:
    """Attach parked cases only when one existing master OR card is an exact match."""
    cases = (
        db.query(SurgicalCase)
        .filter(
            SurgicalCase.date >= start,
            SurgicalCase.date <= end,
            SurgicalCase.or_block_instance_id.is_(None),
            SurgicalCase.status != "cancelled",
        )
        .order_by(SurgicalCase.date, SurgicalCase.start_time, SurgicalCase.id)
        .all()
    )
    placements: list[dict] = []
    missing_time = 0
    ambiguous = 0
    unmatched = 0
    for case in cases:
        sessions = _handoff_sessions(db, case)
        if not sessions:
            missing_time += 1
            continue
        candidates = (
            db.query(ORBlockInstance)
            .join(ORBlockAssignment, ORBlockAssignment.block_instance_id == ORBlockInstance.id)
            .filter(
                ORBlockInstance.date == case.date,
                ORBlockInstance.location_id == case.location_id,
                ORBlockInstance.status.in_(tuple(ACTIVE_BLOCK_STATUSES)),
                ORBlockAssignment.surgeon_id == case.surgeon_id,
            )
            .all()
        )
        candidates = [row for row in candidates if _session_bucket(row) in sessions]
        candidates.sort(key=lambda row: sessions.index(_session_bucket(row)))
        if len(candidates) == 1:
            placements.append({"caseId": case.id, "blockId": candidates[0].id})
        elif len(candidates) > 1:
            ambiguous += 1
        else:
            unmatched += 1
    saved = save_ingest_placements(db, placements=placements) if placements else {"placed": 0, "errors": []}
    return {
        "examined": len(cases),
        "placed": saved.get("placed", 0),
        "missingTime": missing_time,
        "ambiguous": ambiguous,
        "unmatched": unmatched,
        "errors": saved.get("errors", []),
    }


def build_missing_master_cards(db: Session, *, start: date, end: date) -> dict:
    """Fill only empty master-grid slots; never alter an existing schedule card.

    This intentionally does not normalize, fold, prune, replace, or rewrite the
    master template. A pre-existing card wins over the master grid and is counted
    as a conflict if its location differs.
    """
    surgeons = [
        row for row in db.query(Surgeon).filter(
            Surgeon.is_active == True,  # noqa: E712
            Surgeon.staff_type == "physician",
        ).all()
        if surgeon_is_visible(row)
    ]
    surgeon_ids = [row.id for row in surgeons]
    templates = (
        db.query(SurgeonLocationSchedule)
        .options(joinedload(SurgeonLocationSchedule.location))
        .filter(SurgeonLocationSchedule.surgeon_id.in_(surgeon_ids))
        .all()
        if surgeon_ids
        else []
    )
    by_surgeon_day: dict[tuple[int, int], list[SurgeonLocationSchedule]] = {}
    for row in templates:
        by_surgeon_day.setdefault((row.surgeon_id, row.day_of_week), []).append(row)

    off_dates = approved_off_dates(db, surgeon_ids, start, end)
    clinic_created = 0
    blocks_assigned = 0
    blocks_already = 0
    skipped_existing = 0
    skipped_off = 0
    conflicts = 0

    day = start
    while day <= end:
        if day.weekday() <= 4:
            for surgeon in surgeons:
                if (surgeon.id, day) in off_dates:
                    skipped_off += 1
                    continue
                existing = _session_rows(db, surgeon.id, day)
                for template in by_surgeon_day.get((surgeon.id, day.weekday()), []):
                    if template.assignment_type != "assigned" or not template.location_id:
                        continue
                    if not week_pattern_matches(day, template.week_pattern):
                        continue
                    session = (template.session or "").lower()
                    if session not in {"am", "pm"}:
                        continue
                    current = existing.get(session) or existing.get("full")
                    if current is not None:
                        skipped_existing += 1
                        if current.location_id != template.location_id:
                            conflicts += 1
                        # A card that already matches a hospital master slot may
                        # still be missing its OR assignment; fill only that link.
                        if current.location_id != template.location_id:
                            continue
                    else:
                        db.add(ClinicSchedule(
                            surgeon_id=surgeon.id,
                            location_id=template.location_id,
                            date=day,
                            session=session,
                            assignment_type="assigned",
                            notes=None,
                        ))
                        existing[session] = ClinicSchedule(location_id=template.location_id)
                        clinic_created += 1

                    location = template.location
                    if location is None or location.location_type != "hospital":
                        continue
                    result = _place_or_block(db, surgeon, day, session, location)
                    if result == "assigned":
                        blocks_assigned += 1
                    elif result == "already":
                        blocks_already += 1
        day += timedelta(days=1)

    db.commit()
    reconciled = reconcile_parked_cases_after_master_build(db, start=start, end=end)
    return {
        "ok": True,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "clinicCreated": clinic_created,
        "blocksAssigned": blocks_assigned,
        "blocksAlready": blocks_already,
        "skippedExisting": skipped_existing,
        "skippedOff": skipped_off,
        "conflicts": conflicts,
        "cardsFolded": 0,
        "blocksPruned": 0,
        "casesPlaced": reconciled["placed"],
        "casesParked": reconciled["missingTime"] + reconciled["ambiguous"] + reconciled["unmatched"] + len(reconciled["errors"]),
    }
