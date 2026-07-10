from __future__ import annotations

from datetime import date, time, timedelta

from sqlalchemy.orm import Session

from .models import ClinicSchedule, Location, SurgicalCase
from .or_block_service import (
    block_instances_for_range,
    open_blocks_by_day,
    parse_hhmm,
    serialize_block_instance,
)


SESSION_SORT_ORDER = {
    "am": 0,
    "pm": 1,
    "full": 2,
}


def _hhmm_compact(value: str | None) -> str:
    """07:00 → 0700 for compact clinic-grid pills."""
    raw = (value or "").strip()
    if not raw:
        return ""
    return raw.replace(":", "")[:4]


def _block_display_session(block: dict) -> str:
    """Map Block OR session onto AM/PM clinic rows (same layout as location pills)."""
    session = (block.get("session") or "custom").lower()
    if session in ("am", "pm"):
        return session
    start = parse_hhmm(block.get("assignedStart") or block.get("start"), time(7, 0))
    return "am" if start.hour < 12 else "pm"


def aggregate_assigned_or_blocks(blocks: list[dict]) -> list[dict]:
    """
    One pill per location + AM/PM for a surgeon/day.
    Sums case counts; earliest start wins for the label (WG-OR 0700 3 Case).
    """
    groups: dict[tuple, dict] = {}
    for block in blocks:
        session = _block_display_session(block)
        key = (block.get("locationId"), session)
        start = block.get("assignedStart") or block.get("start") or ""
        cases = int(block.get("caseCount") or 0)
        note = (block.get("assignmentNote") or "").strip()
        detail = {
            "assignmentId": block.get("assignmentId"),
            "blockId": block.get("id"),
            "start": start,
            "caseCount": cases,
            "note": note,
            "label": block.get("assignmentLabel") or "",
        }
        if key not in groups:
            loc_abbr = block.get("locationAbbreviation") or block.get("location") or "OR"
            groups[key] = {
                "detailId": f"agg-{block.get('surgeonId')}-{block.get('locationId')}-{session}-{block.get('date')}",
                "surgeonId": block.get("surgeonId"),
                "locationId": block.get("locationId"),
                "location": block.get("location") or "",
                "locationAbbreviation": loc_abbr,
                "locationColor": block.get("locationColor") or "#A7F3D0",
                "session": session,
                "assignedStart": start,
                "caseCount": cases,
                "assignmentNote": note,
                "segments": [detail],
            }
            continue
        group = groups[key]
        group["caseCount"] += cases
        group["segments"].append(detail)
        if start and (not group["assignedStart"] or start < group["assignedStart"]):
            group["assignedStart"] = start
        if note and note not in group["assignmentNote"]:
            group["assignmentNote"] = f"{group['assignmentNote']}; {note}".strip("; ")

    out = []
    for group in groups.values():
        group["segments"].sort(key=lambda row: (row.get("start") or "", row.get("assignmentId") or 0))
        start_compact = _hhmm_compact(group["assignedStart"])
        cases = group["caseCount"]
        case_word = "Case" if cases == 1 else "Cases"
        group["pillLabel"] = f"{group['locationAbbreviation']} {start_compact} {cases} {case_word}".strip()
        group["startCompact"] = start_compact
        out.append(group)
    out.sort(key=lambda row: (SESSION_SORT_ORDER.get(row["session"], 9), row.get("assignedStart") or "", row.get("locationAbbreviation") or ""))
    return out


def clinic_schedule_sort_key(schedule: ClinicSchedule) -> tuple[int, int]:
    return (
        SESSION_SORT_ORDER.get((schedule.session or "full").lower(), 9),
        schedule.id or 0,
    )


def week_days_for_offset(week_offset: int) -> tuple[date, list[date]]:
    today = date.today()
    week_start = today - timedelta(days=today.weekday()) + timedelta(weeks=week_offset)
    return today, [week_start + timedelta(days=i) for i in range(7)]


def surgical_case_json(cases: list[SurgicalCase]) -> list[dict]:
    return [
        {
            "id": case.id,
            "surgeon_id": case.surgeon_id,
            "date": case.date.isoformat(),
            "start": case.start_time.strftime("%H:%M") if case.start_time else "08:00",
            "end": case.end_time.strftime("%H:%M") if case.end_time else None,
            "patient": case.patient_name or "",
            "patient_dob": case.patient_dob or "",
            "patient_phone": case.patient_phone or "",
            "procedure": case.procedure or "",
            "procedure_short": (case.procedure or "")[:80],
            "location_id": case.location_id or "",
            "room": (case.location.name if case.location else None) or case.room_text or "",
            "room_text": case.room_text or "",
            "status": case.status or "scheduled",
            "notes": case.notes or "",
        }
        for case in cases
    ]


def _hour_label(hhmm: str | None) -> str:
    """07:00 → 7, 12:30 → 12:30 for compact Open Block pills."""
    raw = (hhmm or "").strip()
    if not raw or ":" not in raw:
        return raw
    hour_s, minute_s = raw.split(":", 1)
    try:
        hour = int(hour_s)
    except ValueError:
        return raw
    if minute_s == "00":
        return str(hour)
    return f"{hour}:{minute_s}"


def open_block_day_slots(
    hospital_locations: list[Location],
    blocks_by_day_location: dict[date, dict[int, list[dict]]],
    day: date,
) -> list[dict]:
    """
    One equal slot per hospital OR for the Open Block row.
    Prefers a single window per location (earliest start → latest end, summed cases).
    """
    slots = []
    by_location = blocks_by_day_location.get(day, {})
    for location in hospital_locations:
        blocks = sorted(
            by_location.get(location.id, []),
            key=lambda row: (row.get("start") or "", row.get("id") or 0),
        )
        abbr = location.abbreviation or location.name
        color = location.color or "#99F6E4"
        if not blocks:
            slots.append({
                "locationId": location.id,
                "locationAbbreviation": abbr,
                "location": location.name,
                "locationColor": color,
                "blockId": None,
                "start": None,
                "end": None,
                "timeLabel": None,
                "caseCount": 0,
                "status": "empty",
                "pillTitle": f"{abbr} — no block",
            })
            continue
        # One pill per OR: span earliest→latest, sum cases, edit opens first/primary block
        start = blocks[0].get("start")
        end = max((row.get("end") or "") for row in blocks)
        cases = sum(int(row.get("caseCount") or 0) for row in blocks)
        primary = blocks[0]
        # Prefer an open block for edit target when present; else first
        for row in blocks:
            if row.get("status") == "open":
                primary = row
                break
        time_label = f"{_hour_label(start)}-{_hour_label(end)}"
        slots.append({
            "locationId": location.id,
            "locationAbbreviation": abbr,
            "location": location.name,
            "locationColor": color,
            "blockId": primary.get("id"),
            "start": start,
            "end": end,
            "timeLabel": time_label,
            "caseCount": cases,
            "status": primary.get("status") or "open",
            "pillTitle": f"{abbr} {time_label} · {cases} case{'s' if cases != 1 else ''}",
            "blocks": blocks,
        })
    return slots


def page_data(db: Session, week_offset: int) -> dict:
    today, week_days = week_days_for_offset(week_offset)
    all_locations = db.query(Location).filter(
        Location.is_active == True,
    ).order_by(Location.location_type, Location.name).all()
    schedules = db.query(ClinicSchedule).filter(
        ClinicSchedule.date >= week_days[0],
        ClinicSchedule.date <= week_days[6],
    ).all()
    sched_map = {}
    for schedule in sorted(schedules, key=clinic_schedule_sort_key):
        sched_map.setdefault(schedule.surgeon_id, {}).setdefault(schedule.date, []).append(schedule)

    surgical_cases = (
        db.query(SurgicalCase)
        .filter(
            SurgicalCase.date >= week_days[0],
            SurgicalCase.date <= week_days[6],
            SurgicalCase.status != "cancelled",
        )
        .order_by(SurgicalCase.date, SurgicalCase.start_time)
        .all()
    )
    surgical_map = {}
    for case in surgical_cases:
        surgical_map.setdefault(case.surgeon_id, {}).setdefault(case.date, []).append(case)

    surgical_cases_json = {}
    for surgeon_id, day_cases in surgical_map.items():
        for day, cases in day_cases.items():
            surgical_cases_json[f"{surgeon_id}_{day.isoformat()}"] = surgical_case_json(cases)

    # Index by every assigned surgeon (ORBlockAssignment), not legacy first-only assigned_surgeon_id.
    # Then aggregate same location+AM/PM into one clinic-sized pill (sum cases, earliest start).
    assigned_or_blocks_raw: dict = {}
    for block in block_instances_for_range(db, week_days[0], week_days[6]):
        base = serialize_block_instance(block)
        assignments = base.get("assignments") or []
        if not assignments:
            continue
        location_color = block.location.color if block.location and block.location.color else "#A7F3D0"
        for row in assignments:
            surgeon_id = row.get("surgeonId")
            if not surgeon_id:
                continue
            view = dict(base)
            view["surgeonId"] = surgeon_id
            view["surgeon"] = row.get("surgeon")
            view["surgeonInitials"] = row.get("surgeonInitials")
            view["assignedStart"] = row.get("start")
            view["caseCount"] = row.get("caseCount") or 0
            view["assignmentNote"] = row.get("note") or ""
            view["assignmentLabel"] = row.get("label") or ""
            view["assignmentId"] = row.get("id")
            view["locationColor"] = location_color
            view["detailId"] = f"{block.id}-{row.get('id') or surgeon_id}"
            assigned_or_blocks_raw.setdefault(surgeon_id, {}).setdefault(block.date, []).append(view)

    assigned_or_blocks: dict = {}
    for surgeon_id, by_day in assigned_or_blocks_raw.items():
        for day, blocks in by_day.items():
            assigned_or_blocks.setdefault(surgeon_id, {})[day] = aggregate_assigned_or_blocks(blocks)

    hospital_locations = [loc for loc in all_locations if loc.location_type == "hospital"]

    # All Block OR instances for the week (open + assigned) → Open Block day grid
    blocks_by_day_location: dict[date, dict[int, list[dict]]] = {}
    for block in block_instances_for_range(db, week_days[0], week_days[6]):
        if block.status not in ("open", "assigned"):
            continue
        payload = serialize_block_instance(block)
        blocks_by_day_location.setdefault(block.date, {}).setdefault(block.location_id, []).append(payload)

    open_or_day_slots = {
        day: open_block_day_slots(hospital_locations, blocks_by_day_location, day)
        for day in week_days
    }

    return {
        "today": today,
        "week_days": week_days,
        "all_locations": all_locations,
        "clinic_locations": [loc for loc in all_locations if loc.location_type == "clinic"],
        "hospital_locations": hospital_locations,
        "sched_map": sched_map,
        "surgical_map": surgical_map,
        "surgical_cases_json": surgical_cases_json,
        "open_or_blocks": {
            day: [serialize_block_instance(block) for block in blocks]
            for day, blocks in open_blocks_by_day(db, week_days[0], week_days[6]).items()
        },
        "open_or_day_slots": open_or_day_slots,
        "assigned_or_blocks": assigned_or_blocks,
    }
