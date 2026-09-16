from __future__ import annotations

import re
from datetime import date, time, timedelta

from sqlalchemy.orm import Session, joinedload

from .models import ClinicSchedule, Location, SurgicalCase
from .practice_time import practice_today
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


_FAX_CLINIC_TIME_RE = re.compile(r"\b([01]?\d|2[0-3]):([0-5]\d)\b")
_FAX_CLINIC_CHUNK_RE = re.compile(
    r"^([01]?\d|2[0-3]):([0-5]\d)(?:\s+(.+))?$"
)


def _is_hospital_schedule_location(loc: Location | None) -> bool:
    if not loc:
        return False
    abbr = (loc.abbreviation or "").upper()
    ltype = (loc.location_type or "").lower()
    return abbr.endswith("-OR") or ltype in {"hospital", "or"}


def parse_clinic_fax_visit_segments(notes: str) -> list[dict]:
    """Parse `13:00 NIEVES, ROSA; 13:10 PINDER…` from fax clinic notes."""
    text = notes or ""
    first = _FAX_CLINIC_TIME_RE.search(text)
    if not first:
        return []
    body = text[first.start() :]
    segments: list[dict] = []
    seen: set[str] = set()
    for raw in re.split(r"\s*;\s*", body):
        chunk = raw.strip(" ·\t")
        if not chunk:
            continue
        match = _FAX_CLINIC_CHUNK_RE.match(chunk)
        if not match:
            continue
        stamp = f"{int(match.group(1)):02d}:{match.group(2)}"
        label = (match.group(3) or "").strip()
        lower = label.lower()
        if (
            "desk fax" in lower
            or "kno2" in lower
            or "visual sot" in lower
            or "visual png sot" in lower
            or lower.startswith("source=")
        ):
            continue
        if stamp in seen:
            continue
        seen.add(stamp)
        segments.append({
            "start": stamp,
            "caseCount": 1,
            "note": label,
            "label": label,
        })
    return segments[:24]


def clinic_fax_overlay_from_notes(
    schedule: ClinicSchedule,
) -> dict | None:
    """Build a clinic pill overlay from fax times stored in ClinicSchedule.notes."""
    if (schedule.assignment_type or "").lower() != "assigned":
        return None
    loc = schedule.location
    if not loc or _is_hospital_schedule_location(loc):
        return None
    notes = schedule.notes or ""
    note_lower = notes.lower()
    if (
        "desk fax" not in note_lower
        and "source=desk" not in note_lower
        and "visual sot" not in note_lower
    ):
        return None
    segments = parse_clinic_fax_visit_segments(notes)
    if not segments:
        return None
    start = segments[0]["start"]
    count = len(segments)
    abbr = loc.abbreviation or loc.name or "CL"
    visit_word = "Visit" if count == 1 else "Visits"
    return {
        "detailId": f"clinic-fax-{schedule.id}",
        "scheduleId": schedule.id,
        "locationId": schedule.location_id,
        "locationAbbreviation": abbr,
        "location": loc.name or abbr,
        "session": (schedule.session or "pm").lower(),
        "assignedStart": start,
        "startCompact": _hhmm_compact(start),
        "caseCount": count,
        "kind": "clinic",
        "countLabel": visit_word,
        "pillLabel": abbr,
        "pillCountLabel": f"{count} {visit_word.lower()}",
        "segments": segments,
        "notes": notes,
    }


def build_clinic_fax_overlays(sched_map: dict) -> dict[int, dict]:
    overlays: dict[int, dict] = {}
    for by_day in sched_map.values():
        for schedules in by_day.values():
            for schedule in schedules:
                overlay = clinic_fax_overlay_from_notes(schedule)
                if overlay:
                    overlays[schedule.id] = overlay
    return overlays


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
    Sums case counts; earliest start is kept for detail only.
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
        group["pillLabel"] = group["locationAbbreviation"]
        group["pillCountLabel"] = f"{cases} {case_word.lower()}"
        group["startCompact"] = start_compact
        group["kind"] = "or"
        group["countLabel"] = case_word
        out.append(group)
    out.sort(key=lambda row: (SESSION_SORT_ORDER.get(row["session"], 9), row.get("assignedStart") or "", row.get("locationAbbreviation") or ""))
    return out


def collapse_daily_or_blocks(assigned_or_blocks: dict) -> dict:
    """Enforce one OR card per surgeon/day on the Clinic / OR grid."""
    for surgeon_id, by_day in assigned_or_blocks.items():
        for day, blocks in list(by_day.items()):
            if len(blocks) <= 1:
                continue

            locations: list[str] = []
            location_names: list[str] = []
            color = None
            segments: list[dict] = []
            fallback_count = 0
            notes: list[str] = []

            for block in blocks:
                loc_abbr = block.get("locationAbbreviation") or block.get("location") or "OR"
                loc_name = block.get("location") or loc_abbr
                if loc_abbr not in locations:
                    locations.append(loc_abbr)
                if loc_name and loc_name not in location_names:
                    location_names.append(loc_name)
                if not color and block.get("locationColor"):
                    color = block.get("locationColor")
                note = (block.get("assignmentNote") or "").strip()
                if note and note not in notes:
                    notes.append(note)
                fallback_count += int(block.get("caseCount") or 0)

                block_segments = list(block.get("segments") or [])
                if block_segments:
                    for segment in block_segments:
                        row = dict(segment)
                        row.setdefault("locationAbbreviation", loc_abbr)
                        row.setdefault("location", loc_name)
                        segments.append(row)
                    continue

                start = block.get("assignedStart") or block.get("start") or ""
                segments.append({
                    "start": start,
                    "caseCount": int(block.get("caseCount") or 0),
                    "note": note,
                    "label": block.get("assignmentLabel") or loc_abbr,
                    "locationAbbreviation": loc_abbr,
                    "location": loc_name,
                    "assignmentId": block.get("assignmentId"),
                    "blockId": block.get("id"),
                })

            has_real_cases = any(row.get("patient") or row.get("caseId") for row in segments)
            if has_real_cases:
                segments = [
                    row for row in segments
                    if row.get("patient") or row.get("caseId") or int(row.get("caseCount") or 0) > 0
                ]
            segments.sort(
                key=lambda row: (
                    row.get("start") or "",
                    row.get("caseId") or row.get("assignmentId") or row.get("blockId") or 0,
                    row.get("locationAbbreviation") or "",
                )
            )
            assigned_start = next((row.get("start") for row in segments if row.get("start")), "")
            case_count = sum(int(row.get("caseCount") or 0) for row in segments) or fallback_count
            case_word = "Case" if case_count == 1 else "Cases"
            display_location = locations[0] if len(locations) == 1 else "OR"
            display_name = location_names[0] if len(location_names) == 1 else "Multiple OR locations"
            session = "am"
            if assigned_start:
                parsed = parse_hhmm(assigned_start, time(7, 0))
                session = "am" if parsed < time(12, 0) else "pm"

            merged = dict(blocks[0])
            merged.update({
                "detailId": f"daily-or-{surgeon_id}-{day.isoformat()}",
                "surgeonId": surgeon_id,
                "locationId": None if len(locations) > 1 else blocks[0].get("locationId"),
                "location": display_name,
                "locationAbbreviation": display_location,
                "locationColor": color or blocks[0].get("locationColor") or "#A7F3D0",
                "session": session,
                "assignedStart": assigned_start,
                "caseCount": case_count,
                "assignmentNote": "; ".join(notes),
                "segments": segments,
                "pillLabel": display_location,
                "pillCountLabel": f"{case_count} {case_word.lower()}",
                "startCompact": _hhmm_compact(assigned_start),
                "kind": "or",
                "countLabel": case_word,
            })
            by_day[day] = [merged]
    return assigned_or_blocks


def remove_zero_case_or_cards(assigned_or_blocks: dict) -> dict:
    """Hide paper/static OR cards from the grid until an actual case exists."""
    cleaned: dict = {}
    for surgeon_id, by_day in assigned_or_blocks.items():
        for day, blocks in by_day.items():
            visible = [
                block for block in blocks
                if int(block.get("caseCount") or 0) > 0
            ]
            if visible:
                cleaned.setdefault(surgeon_id, {})[day] = visible
    return cleaned


def enforce_two_card_daily_limit(
    sched_map: dict,
    assigned_or_blocks: dict,
    or_block_overlays: dict[int, dict],
    clinic_fax_overlays: dict[int, dict],
) -> tuple[dict, dict, dict, dict]:
    """Clinic / OR grid invariant: at most one schedule card and one OR card per surgeon/day."""
    limited_sched: dict = {}
    kept_schedule_ids: set[int] = set()
    for surgeon_id, by_day in sched_map.items():
        for day, schedules in by_day.items():
            ordered = sorted(
                schedules,
                key=lambda schedule: (
                    1 if _is_hospital_schedule_location(schedule.location) else 0,
                    *clinic_schedule_sort_key(schedule),
                ),
            )
            if not ordered:
                continue
            kept = ordered[0]
            limited_sched.setdefault(surgeon_id, {})[day] = [kept]
            if kept.id:
                kept_schedule_ids.add(kept.id)

    limited_blocks: dict = {}
    for surgeon_id, by_day in assigned_or_blocks.items():
        for day, blocks in by_day.items():
            ordered = sorted(
                blocks,
                key=lambda row: (
                    SESSION_SORT_ORDER.get((row.get("session") or "full").lower(), 9),
                    row.get("assignedStart") or "",
                    row.get("detailId") or "",
                ),
            )
            if ordered:
                limited_blocks.setdefault(surgeon_id, {})[day] = [ordered[0]]

    limited_or_overlays = {
        schedule_id: overlay
        for schedule_id, overlay in or_block_overlays.items()
        if schedule_id in kept_schedule_ids
    }
    limited_clinic_overlays = {
        schedule_id: overlay
        for schedule_id, overlay in clinic_fax_overlays.items()
        if schedule_id in kept_schedule_ids
    }
    return limited_sched, limited_blocks, limited_or_overlays, limited_clinic_overlays


def _sessions_compatible(schedule_session: str | None, block_session: str | None) -> bool:
    sched = (schedule_session or "full").lower()
    block = (block_session or "am").lower()
    if sched == "full":
        return True
    return sched == block


def _enrich_or_block_with_live_cases(block: dict, cases: list[SurgicalCase]) -> dict:
    """Replace assignment caseCount/segments with real SurgicalCase rows for the pill."""
    loc_id = block.get("locationId")
    session = _block_display_session(block)
    matching = [
        case
        for case in cases
        if not loc_id or case.location_id == loc_id
        if _case_display_session(case) == session
    ]
    if not matching:
        return block
    matching = sorted(
        matching,
        key=lambda case: (case.start_time or time(0, 0), case.id or 0),
    )
    segments = []
    for case in matching:
        stamp = case.start_time.strftime("%H:%M") if case.start_time else ""
        patient = (case.patient_name or "").strip() or "Case"
        proc = (case.procedure or "").strip()
        room = (case.room_text or "").strip()
        secondary = " · ".join(part for part in (proc[:80], room) if part)
        segments.append({
            "start": stamp,
            "caseCount": 1,
            "note": secondary,
            "label": patient,
            "patient": patient,
            "procedure": proc[:80],
            "room": room,
            "caseId": case.id,
        })
    out = dict(block)
    out["caseCount"] = len(segments)
    out["segments"] = segments
    start = segments[0]["start"] if segments else out.get("assignedStart")
    if start:
        out["assignedStart"] = start
    start_compact = _hhmm_compact(out.get("assignedStart"))
    case_word = "Case" if len(segments) == 1 else "Cases"
    abbr = out.get("locationAbbreviation") or out.get("location") or "OR"
    out["startCompact"] = start_compact
    out["countLabel"] = case_word
    out["kind"] = "or"
    out["pillLabel"] = abbr
    out["pillCountLabel"] = f"{len(segments)} {case_word.lower()}"
    return out


def enrich_or_blocks_with_live_cases(
    assigned_or_blocks: dict,
    surgical_map: dict,
) -> dict:
    enriched: dict = {}
    for surgeon_id, by_day in assigned_or_blocks.items():
        for day, blocks in by_day.items():
            day_cases = surgical_map.get(surgeon_id, {}).get(day, []) or []
            enriched.setdefault(surgeon_id, {})[day] = [
                _enrich_or_block_with_live_cases(block, day_cases) for block in blocks
            ]
    return enriched


def enrich_or_overlays_with_live_cases(
    overlays: dict[int, dict],
    sched_map: dict,
    surgical_map: dict,
) -> dict[int, dict]:
    out: dict[int, dict] = {}
    for schedule_id, block in overlays.items():
        surgeon_id = block.get("surgeonId")
        day = None
        raw_day = block.get("date")
        if isinstance(raw_day, date):
            day = raw_day
        elif isinstance(raw_day, str) and raw_day:
            try:
                day = date.fromisoformat(raw_day[:10])
            except ValueError:
                day = None
        if day is None or not surgeon_id:
            for sid, by_day in sched_map.items():
                for d, schedules in by_day.items():
                    if any(s.id == schedule_id for s in schedules):
                        surgeon_id = surgeon_id or sid
                        day = d
                        break
                if day is not None:
                    break
        day_cases = (
            surgical_map.get(surgeon_id, {}).get(day, []) or []
            if day and surgeon_id
            else []
        )
        out[schedule_id] = _enrich_or_block_with_live_cases(block, day_cases)
    return out


def _case_display_session(case: SurgicalCase) -> str:
    start = case.start_time or time(7, 0)
    return "am" if start < time(12, 0) else "pm"


def append_unlinked_surgical_case_blocks(
    assigned_or_blocks: dict,
    surgical_map: dict,
    or_block_overlays: dict[int, dict],
) -> dict:
    """Surface surgical cases even when static Block OR links are missing.

    Fax cleanup can land a true case before the static card is repaired. The
    portal still has to show counts/details instead of a bare Hospital chip.
    """
    represented: set[tuple[int, date, int, str]] = set()
    for surgeon_id, by_day in assigned_or_blocks.items():
        for day, blocks in by_day.items():
            for block in blocks:
                loc_id = block.get("locationId")
                session = _block_display_session(block)
                if loc_id:
                    represented.add((surgeon_id, day, int(loc_id), session))
    for block in or_block_overlays.values():
        surgeon_id = block.get("surgeonId")
        loc_id = block.get("locationId")
        raw_day = block.get("date")
        day = raw_day if isinstance(raw_day, date) else None
        if not day and isinstance(raw_day, str) and raw_day:
            try:
                day = date.fromisoformat(raw_day[:10])
            except ValueError:
                day = None
        if surgeon_id and loc_id and day:
            represented.add((int(surgeon_id), day, int(loc_id), _block_display_session(block)))

    grouped: dict[tuple[int, date, int, str], list[SurgicalCase]] = {}
    for surgeon_id, by_day in surgical_map.items():
        for day, cases in by_day.items():
            for case in cases:
                if case.or_block_instance_id or not case.location_id:
                    continue
                if not _is_hospital_schedule_location(case.location):
                    continue
                session = _case_display_session(case)
                key = (surgeon_id, day, case.location_id, session)
                if key in represented:
                    continue
                grouped.setdefault(key, []).append(case)

    for (surgeon_id, day, location_id, session), cases in grouped.items():
        location = cases[0].location
        if not location:
            continue
        sorted_cases = sorted(cases, key=lambda row: (row.start_time or time(0, 0), row.id or 0))
        segments = []
        for case in sorted_cases:
            stamp = case.start_time.strftime("%H:%M") if case.start_time else ""
            proc = (case.procedure or "").strip()
            room = (case.room_text or "").strip()
            secondary = " · ".join(part for part in (proc[:80], room) if part)
            segments.append({
                "start": stamp,
                "caseCount": 1,
                "note": secondary,
                "label": case.patient_name or "Case",
                "patient": case.patient_name or "Case",
                "procedure": proc[:80],
                "room": room,
                "caseId": case.id,
            })
        start = segments[0]["start"] if segments else ""
        count = len(segments)
        case_word = "Case" if count == 1 else "Cases"
        abbr = location.abbreviation or location.name or "OR"
        fallback = {
            "detailId": f"case-fallback-{surgeon_id}-{location_id}-{session}-{day.isoformat()}",
            "surgeonId": surgeon_id,
            "locationId": location_id,
            "location": location.name or abbr,
            "locationAbbreviation": abbr,
            "locationColor": location.color or "#A7F3D0",
            "session": session,
            "assignedStart": start,
            "caseCount": count,
            "segments": segments,
            "pillLabel": abbr,
            "pillCountLabel": f"{count} {case_word.lower()}",
            "startCompact": _hhmm_compact(start),
            "kind": "or",
            "countLabel": case_word,
            "assignmentNote": "Static Block OR card missing; showing scheduled cases.",
        }
        assigned_or_blocks.setdefault(surgeon_id, {}).setdefault(day, []).append(fallback)
        assigned_or_blocks[surgeon_id][day].sort(
            key=lambda row: (
                SESSION_SORT_ORDER.get((row.get("session") or "full").lower(), 9),
                row.get("assignedStart") or "",
                row.get("locationAbbreviation") or "",
            )
        )
    return assigned_or_blocks


def merge_or_blocks_into_clinic_grid(
    sched_map: dict,
    assigned_or_blocks: dict,
) -> tuple[dict[int, dict], dict]:
    """
    Append Block OR start/cases onto the ClinicSchedule hospital pill (SSOT grid).
    Drop the duplicate Block OR pill when location+session already exists on the grid.
    """
    overlays: dict[int, dict] = {}
    remaining: dict = {}

    for surgeon_id, by_day in assigned_or_blocks.items():
        remaining.setdefault(surgeon_id, {})
        for day, blocks in by_day.items():
            schedules = list(sched_map.get(surgeon_id, {}).get(day, []) or [])
            used: set[int] = set()
            for schedule in schedules:
                if (schedule.assignment_type or "").lower() != "assigned":
                    continue
                if not _is_hospital_schedule_location(schedule.location):
                    continue
                for idx, block in enumerate(blocks):
                    if idx in used:
                        continue
                    if block.get("locationId") != schedule.location_id:
                        continue
                    if not _sessions_compatible(schedule.session, block.get("session")):
                        continue
                    overlays[schedule.id] = block
                    used.add(idx)
                    break
            leftover = [block for idx, block in enumerate(blocks) if idx not in used]
            if leftover:
                remaining[surgeon_id][day] = leftover

    remaining = {
        sid: {d: blks for d, blks in days.items() if blks}
        for sid, days in remaining.items()
        if any(days.values())
    }
    return overlays, remaining


def clinic_schedule_sort_key(schedule: ClinicSchedule) -> tuple[int, int]:
    return (
        SESSION_SORT_ORDER.get((schedule.session or "full").lower(), 9),
        schedule.id or 0,
    )


def week_days_for_offset(week_offset: int) -> tuple[date, list[date]]:
    today = practice_today()
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
            "assisting_surgeon_id": case.assisting_surgeon_id or "",
            "assisting_surgeon": case.assisting_surgeon.full_name if case.assisting_surgeon else "",
        }
        for case in cases
    ]


def _hour_label(hhmm: str | None) -> str:
    """07:00 → 7:00, 12:30 → 12:30 — keep minutes so the time line stays tidy."""
    raw = (hhmm or "").strip()
    if not raw or ":" not in raw:
        return raw
    hour_s, minute_s = raw.split(":", 1)[:2]
    try:
        hour = int(hour_s)
        minute = int(minute_s[:2])
    except ValueError:
        return raw
    return f"{hour}:{minute:02d}"


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
            "caseCountLabel": f"{cases} case{'s' if cases != 1 else ''}",
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
    schedules = (
        db.query(ClinicSchedule)
        .options(joinedload(ClinicSchedule.location))
        .filter(
            ClinicSchedule.date >= week_days[0],
            ClinicSchedule.date <= week_days[6],
        )
        .all()
    )
    sched_map = {}
    for schedule in sorted(schedules, key=clinic_schedule_sort_key):
        sched_map.setdefault(schedule.surgeon_id, {}).setdefault(schedule.date, []).append(schedule)

    surgical_cases = (
        db.query(SurgicalCase)
        .options(joinedload(SurgicalCase.location))
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

    or_block_overlays, assigned_or_blocks = merge_or_blocks_into_clinic_grid(sched_map, assigned_or_blocks)
    assigned_or_blocks = enrich_or_blocks_with_live_cases(assigned_or_blocks, surgical_map)
    or_block_overlays = enrich_or_overlays_with_live_cases(
        or_block_overlays, sched_map, surgical_map
    )
    assigned_or_blocks = append_unlinked_surgical_case_blocks(
        assigned_or_blocks, surgical_map, or_block_overlays
    )
    assigned_or_blocks = collapse_daily_or_blocks(assigned_or_blocks)
    assigned_or_blocks = remove_zero_case_or_cards(assigned_or_blocks)
    clinic_fax_overlays = build_clinic_fax_overlays(sched_map)
    sched_map, assigned_or_blocks, or_block_overlays, clinic_fax_overlays = enforce_two_card_daily_limit(
        sched_map,
        assigned_or_blocks,
        or_block_overlays,
        clinic_fax_overlays,
    )

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

    from .off_conflict_service import build_clinic_off_display

    off_display = build_clinic_off_display(
        db,
        week_days[0],
        week_days[6],
        sched_map=sched_map,
        surgical_map=surgical_map,
        assigned_or_blocks=assigned_or_blocks,
        or_block_overlays=or_block_overlays,
    )

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
        "or_block_overlays": or_block_overlays,
        "clinic_fax_overlays": clinic_fax_overlays,
        "off_map": off_display["off_map"],
        "off_conflicts": off_display["off_conflicts"],
        "off_conflict_dicts": off_display["off_conflict_dicts"],
        "show_off_schedule_ids": off_display["show_off_schedule_ids"],
        "show_off_or_keys": off_display["show_off_or_keys"],
        "hide_empty_or_blocks": off_display["hide_empty_or_blocks"],
        "conflict_keys": off_display["conflict_keys"],
        "synthetic_off_days": off_display["synthetic_off_days"],
    }
