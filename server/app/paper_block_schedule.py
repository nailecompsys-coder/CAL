"""Paper weekly block schedule (surgeon AM/PM) → Clinics/OR + Block OR.

This is hospital *block* time, not room inventory. One AM/PM window at a
hospital; the scheduler places one surgeon or both. Surgeons listed on the
block must see that window on CAL even with zero cases — they still report,
because cases are often added early morning. A session with no block is off
until clinic. Clermont is clinic-only (no OR).

Week 1 / 3 / 5 = nth weekday of the month (Sep 14 2026 is week 2).
"""
from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy.orm import Session

from .admin_schedule_template_clinic_service import save_template_cell_value
from .admin_schedule_template_common import approved_off_dates
from .models import ClinicSchedule, Location, ORBlockInstance, Surgeon, SurgeonLocationSchedule
from .or_block_service import (
    BlockORCreateInput,
    SESSION_DEFAULTS,
    assign_block,
    create_or_blocks,
)
from .surgeon_visibility import surgeon_is_visible

START = date(2026, 9, 14)
END = date(2027, 6, 14)

# (day_of_week 0=Mon, session) → (location abbreviation, weeks or None=every week)
PAPER: dict[str, dict[tuple[int, str], tuple[str, frozenset[int] | None]]] = {
    "JF": {
        (0, "am"): ("AP-OR", None),
        (0, "pm"): ("AP-OV", None),
        (1, "am"): ("WG-OR", None),
        (1, "pm"): ("WG-OV", None),
        (2, "am"): ("MN-OR", None),
        (3, "am"): ("WG-OR", None),
        (3, "pm"): ("WG-OV", None),
        (4, "am"): ("WG-OR", None),
    },
    "CJ": {
        (0, "am"): ("MN-OR", None),
        (1, "am"): ("WG-OR", None),
        (1, "pm"): ("CL-OV", None),
        (2, "am"): ("CL-OV", None),
        (3, "am"): ("CL-OV", None),
        (3, "pm"): ("MN-OR", None),
    },
    "JB": {
        (0, "am"): ("CL-OV", None),
        (1, "am"): ("CL-OV", None),
        (1, "pm"): ("MN-OR", None),
        (2, "am"): ("WG-OR", None),
        (3, "am"): ("MN-OR", None),
        (3, "pm"): ("CL-OV", None),
    },
    "AS": {
        (0, "am"): ("WG-OR", frozenset({1, 3, 5})),
        (0, "pm"): ("CL-OV", None),
        (1, "am"): ("MN-OR", None),
        (2, "am"): ("AP-OR", None),
        (2, "pm"): ("AP-OV", None),
        (3, "am"): ("WG-OV", None),
        (4, "am"): ("WG-OR", frozenset({3})),
    },
    "OK": {
        (0, "am"): ("WG-OR", None),
        (0, "pm"): ("DP-OV", None),
        (1, "am"): ("WG-OV", None),
        (2, "am"): ("AP-OV", None),
        (2, "pm"): ("AP-OR", None),
        (3, "pm"): ("WG-OR", None),
        (4, "am"): ("WG-OV", None),
    },
    "LW": {
        (0, "am"): ("AP-OV", None),
        (0, "pm"): ("AP-OR", None),
        (1, "am"): ("AL-OV", None),
        (2, "am"): ("AL-OR", None),
        (4, "am"): ("AP-OV", None),
    },
    "JP": {
        (2, "pm"): ("CL-OV", None),
        (4, "am"): ("CL-OV", None),
        (4, "pm"): ("MN-OR", None),
    },
    "GY": {
        (1, "am"): ("AL-OR", None),
        (1, "pm"): ("AL-OV", None),
        (2, "am"): ("LM-OV", None),
        (2, "pm"): ("AL-OR", None),
        (4, "am"): ("AL-OR", None),
        (4, "pm"): ("AL-OR", None),
    },
    "LN": {
        (0, "am"): ("LM-OV", None),
        (0, "pm"): ("AL-OR", None),
        (3, "am"): ("AL-OR", None),
        (3, "pm"): ("AL-OV", None),
        (4, "am"): ("AL-OR", None),
        (4, "pm"): ("AL-OR", None),
    },
    "NF": {
        (0, "am"): ("AL-OR", None),
        (0, "pm"): ("LM-OV", None),
        (3, "am"): ("AL-OR", None),
        (3, "pm"): ("AL-OR", None),
        (4, "am"): ("AL-OR", None),
        (4, "pm"): ("AL-OR", None),
    },
    "JD": {
        (4, "am"): ("AL-OV", None),
        (4, "pm"): ("AL-OR", None),
    },
}


def month_week(day: date) -> int:
    """1–5: first Mon–Sun slice is week 1, so Sep 14 2026 (2nd Monday) is week 2."""
    return (day.day - 1) // 7 + 1


def paper_cell(initials: str, day: date, session: str) -> str | None:
    spec = PAPER.get(initials, {}).get((day.weekday(), session))
    if not spec:
        return None
    abbrev, weeks = spec
    if weeks is not None and month_week(day) not in weeks:
        return None
    return abbrev


def _locations_by_abbrev(db: Session) -> dict[str, Location]:
    out: dict[str, Location] = {}
    for loc in db.query(Location).filter(Location.is_active == True).all():  # noqa: E712
        key = (loc.abbreviation or "").strip().upper()
        if key:
            out[key] = loc
    return out


def _physicians_by_initials(db: Session) -> dict[str, Surgeon]:
    out: dict[str, Surgeon] = {}
    for surgeon in db.query(Surgeon).filter(Surgeon.is_active == True).all():  # noqa: E712
        if not surgeon_is_visible(surgeon):
            continue
        if (surgeon.staff_type or "physician") != "physician":
            continue
        key = (surgeon.initials or "").strip().upper()
        if key in PAPER:
            out[key] = surgeon
    return out


def _blocks_for_slot(db: Session, location_id: int, day: date, session: str) -> list[ORBlockInstance]:
    start, end = SESSION_DEFAULTS[session]
    rows = (
        db.query(ORBlockInstance)
        .filter(
            ORBlockInstance.location_id == location_id,
            ORBlockInstance.date == day,
            ORBlockInstance.status.in_(("open", "assigned")),
            ORBlockInstance.start_time < end,
            ORBlockInstance.end_time > start,
        )
        .order_by(ORBlockInstance.start_time, ORBlockInstance.id)
        .all()
    )
    return rows


def _surgeon_on_block(block: ORBlockInstance, surgeon_id: int) -> bool:
    if block.assigned_surgeon_id == surgeon_id:
        return True
    return any(row.surgeon_id == surgeon_id for row in (block.assignments or []))


def _shared_time_block(db: Session, location: Location, day: date, session: str) -> ORBlockInstance | None:
    """One practice window per hospital + day + AM/PM. No room. Scheduler places one or both."""
    blocks = _blocks_for_slot(db, location.id, day, session)
    blanks = [row for row in blocks if not (row.room_text or "").strip()]
    if blanks:
        return blanks[0]
    start, end = SESSION_DEFAULTS[session]
    try:
        created = create_or_blocks(
            db,
            BlockORCreateInput(
                name=f"{location.name} {session.upper()}",
                start_date=day,
                end_date=day,
                weekdays=[day.weekday()],
                location_ids=[location.id],
                session=session,
                start_time=start,
                end_time=end,
                recurrence="once",
                owner_type="practice",
            ),
        )
    except ValueError:
        created = {}
    if created.get("instance_ids"):
        row = db.get(ORBlockInstance, created["instance_ids"][0])
        if row and not (row.room_text or "").strip():
            return row
    blanks = [row for row in _blocks_for_slot(db, location.id, day, session) if not (row.room_text or "").strip()]
    return blanks[0] if blanks else None


def sync_weekly_templates(db: Session, surgeons: dict[str, Surgeon], locations: dict[str, Location]) -> int:
    """Write repeating weekly cells. Week 1/3/5 cells stay off the weekly template."""
    updated = 0
    for initials, cells in PAPER.items():
        surgeon = surgeons.get(initials)
        if not surgeon:
            continue
        weekly: dict[tuple[int, str], str] = {}
        for (dow, session), (abbrev, weeks) in cells.items():
            if weeks is None:
                weekly[(dow, session)] = abbrev
        for dow in range(5):
            for session in ("am", "pm"):
                abbrev = weekly.get((dow, session))
                if abbrev:
                    loc = locations[abbrev]
                    save_template_cell_value(
                        db, surgeon.id, dow, session, loc.id, "assigned",
                    )
                else:
                    existing = db.query(SurgeonLocationSchedule).filter(
                        SurgeonLocationSchedule.surgeon_id == surgeon.id,
                        SurgeonLocationSchedule.day_of_week == dow,
                        SurgeonLocationSchedule.session == session,
                    ).first()
                    if existing:
                        db.delete(existing)
                        db.commit()
                updated += 1
    return updated


def _replace_clinic_day(
    db: Session,
    surgeon: Surgeon,
    day: date,
    locations: dict[str, Location],
) -> tuple[int, int]:
    existing = (
        db.query(ClinicSchedule)
        .filter(ClinicSchedule.surgeon_id == surgeon.id, ClinicSchedule.date == day)
        .all()
    )
    for row in existing:
        db.delete(row)
    db.flush()
    created = 0
    for session in ("am", "pm"):
        abbrev = paper_cell(surgeon.initials, day, session)
        if not abbrev:
            continue
        loc = locations[abbrev]
        db.add(ClinicSchedule(
            surgeon_id=surgeon.id,
            location_id=loc.id,
            date=day,
            session=session,
            assignment_type="assigned",
            notes=None,
        ))
        created += 1
    return created, len(existing)


def _place_or_block(
    db: Session,
    surgeon: Surgeon,
    day: date,
    session: str,
    location: Location,
) -> str:
    if location.location_type != "hospital":
        return "skip_clinic"
    target = _shared_time_block(db, location, day, session)
    if target is None:
        return "missing_block"
    if _surgeon_on_block(target, surgeon.id):
        return "already"
    assign_block(
        db,
        target.id,
        surgeon.id,
        assignment_note="Paper block schedule",
        notify=False,
    )
    return "assigned"


def apply_paper_block_schedule(
    db: Session,
    *,
    start: date = START,
    end: date = END,
    write_templates: bool = True,
    write_clinic: bool = True,
    write_blocks: bool = True,
) -> dict:
    locations = _locations_by_abbrev(db)
    required = {abbrev for cells in PAPER.values() for abbrev, _weeks in cells.values()}
    missing_locs = sorted(required - set(locations))
    if missing_locs:
        raise ValueError("Missing locations: " + ", ".join(missing_locs))
    clermont = locations["CL-OV"]
    if clermont.location_type != "clinic":
        raise ValueError("CL-OV must be a clinic; Clermont has no OR")

    surgeons = _physicians_by_initials(db)
    missing_docs = sorted(set(PAPER) - set(surgeons))
    if missing_docs:
        raise ValueError("Missing physicians: " + ", ".join(missing_docs))

    template_cells = sync_weekly_templates(db, surgeons, locations) if write_templates else 0
    off_dates = approved_off_dates(db, [s.id for s in surgeons.values()], start, end)

    clinic_created = 0
    clinic_cleared = 0
    skipped_off = 0
    blocks_assigned = 0
    blocks_already = 0

    day = start
    while day <= end:
        if day.weekday() <= 4:
            for initials, surgeon in surgeons.items():
                if (surgeon.id, day) in off_dates:
                    skipped_off += 1
                    continue
                if write_clinic:
                    created, cleared = _replace_clinic_day(db, surgeon, day, locations)
                    clinic_created += created
                    clinic_cleared += cleared
                if write_blocks:
                    for session in ("am", "pm"):
                        abbrev = paper_cell(initials, day, session)
                        if not abbrev or not abbrev.endswith("-OR"):
                            continue
                        result = _place_or_block(db, surgeon, day, session, locations[abbrev])
                        if result == "assigned":
                            blocks_assigned += 1
                        elif result == "already":
                            blocks_already += 1
        day += timedelta(days=1)

    db.commit()
    return {
        "ok": True,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "templateCells": template_cells,
        "clinicCreated": clinic_created,
        "clinicCleared": clinic_cleared,
        "skippedOff": skipped_off,
        "blocksAssigned": blocks_assigned,
        "blocksAlready": blocks_already,
        "physicians": sorted(surgeons),
    }
