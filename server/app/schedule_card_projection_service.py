"""Read-only projection of permanent schedule cards for the admin calendar."""

from __future__ import annotations

from collections import defaultdict
from datetime import date, time
import re

from sqlalchemy.orm import Session, joinedload

from .admin_clinic_schedule_page_service import parse_clinic_fax_visit_segments
from .models import ClinicSchedule, DayOff, Location, ScheduleCard, Surgeon, SurgicalCase
from .native_dayoff_support import segment_for_date


def _session_for_time(value: time | None) -> str:
    return "pm" if value and value >= time(12, 0) else "am"


def _normal(value: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", "", (value or "").lower())


def _parse_clock(value: str | None) -> time | None:
    try:
        return time.fromisoformat((value or "").strip())
    except ValueError:
        return None


def _aprima_location_map(locations: list[Location]) -> dict[str, Location]:
    result: dict[str, Location] = {}
    for location in locations:
        for label in (location.name, location.abbreviation):
            if label:
                result[_normal(label)] = location
    cbo = next((row for row in locations if (row.abbreviation or "").upper() == "CBO-OV"), None)
    if cbo:
        result[_normal("Surgery One")] = cbo
        result[_normal("Clermont Business Office")] = cbo
    return result


def _aprima_rows_by_slot(
    db: Session,
    start: date,
    end: date,
    surgeons: list[Surgeon],
    locations: list[Location],
) -> dict[tuple[int, date, str], list[dict]]:
    from .aprima_cache_service import patient_appointments_for_api
    from .aprima_schedule_service import (
        appointment_belongs_to_surgeon,
        is_surgery_appointment,
        resolve_aprima_facility_name,
    )

    payload = patient_appointments_for_api(db, start, end)
    location_map = _aprima_location_map(locations)
    result: dict[tuple[int, date, str], list[dict]] = defaultdict(list)
    for row in payload.get("appointments") or []:
        try:
            day = date.fromisoformat((row.get("date") or "").strip())
        except ValueError:
            continue
        clock = _parse_clock(row.get("start"))
        if not clock:
            continue
        surgeon = next((item for item in surgeons if appointment_belongs_to_surgeon(row, item)), None)
        if not surgeon:
            continue
        is_surgery = is_surgery_appointment(row)
        facility = resolve_aprima_facility_name(
            row.get("serviceSite") or "",
            is_surgery=is_surgery,
        )
        location = location_map.get(_normal(facility))
        if not location:
            location = location_map.get(_normal(row.get("serviceSite")))
        if not location:
            continue
        patient = (row.get("patientName") or "").strip()
        result[(surgeon.id, day, _session_for_time(clock))].append({
            "start": clock.strftime("%H:%M"),
            "label": patient,
            "patient_key": _normal(patient),
            "location": location,
            "is_surgery": is_surgery,
            "room": (row.get("room") or row.get("serviceSite") or "").strip(),
            "source": "aprima",
        })
    return result


def _clinic_times_by_day(rows: list[ClinicSchedule]) -> dict[tuple[int, date], list[time]]:
    result: dict[tuple[int, date], list[time]] = defaultdict(list)
    for row in rows:
        for segment in parse_clinic_fax_visit_segments(row.notes or ""):
            try:
                result[(row.surgeon_id, row.date)].append(time.fromisoformat(segment["start"]))
            except (KeyError, TypeError, ValueError):
                continue
    return result


def _case_session(row: SurgicalCase, clinic_times: dict[tuple[int, date], list[time]]) -> str:
    value = row.start_time
    if value is None or not time(11, 30) <= value < time(12):
        return _session_for_time(value)
    prior = [slot for slot in clinic_times.get((row.surgeon_id, row.date), []) if slot < value]
    if not prior:
        return "am"
    gap = value.hour * 60 + value.minute - max(slot.hour * 60 + slot.minute for slot in prior)
    return "pm" if gap >= 30 else "am"


def _session_is_off(day_off: DayOff, day: date, session: str) -> bool:
    segment = segment_for_date(day_off, day) or {}
    if segment.get("isFullDay", day_off.is_full_day if day_off.is_full_day is not None else True):
        return True
    start = segment.get("start") or (day_off.start_time.strftime("%H:%M") if day_off.start_time else "")
    end = segment.get("end") or (day_off.end_time.strftime("%H:%M") if day_off.end_time else "")
    try:
        start_time = time.fromisoformat(start)
        end_time = time.fromisoformat(end)
    except ValueError:
        return False
    if session == "am":
        return start_time < time(12, 0)
    return end_time > time(12, 0)


def _clinic_visit_counts(rows: list[ClinicSchedule]) -> dict[tuple[int, date, str, int], int]:
    counts: dict[tuple[int, date, str, int], int] = defaultdict(int)
    for row in rows:
        if not row.location_id:
            continue
        segments = parse_clinic_fax_visit_segments(row.notes or "")
        if segments:
            for segment in segments:
                try:
                    hour = int((segment.get("start") or "00:00").split(":", 1)[0])
                except ValueError:
                    hour = 0
                session = "pm" if hour >= 12 else "am"
                counts[(row.surgeon_id, row.date, session, row.location_id)] += 1
            continue
        session = (row.session or "am").lower()
        if session in {"am", "pm"}:
            counts[(row.surgeon_id, row.date, session, row.location_id)] += 0
    return counts


def card_grid_page_data(db: Session, start: date, end: date) -> dict:
    """Return exactly the permanent AM/PM cards. This function never writes."""
    cards = (
        db.query(ScheduleCard)
        .options(joinedload(ScheduleCard.surgeon), joinedload(ScheduleCard.effective_location))
        .filter(ScheduleCard.date >= start, ScheduleCard.date <= end)
        .order_by(ScheduleCard.surgeon_id, ScheduleCard.date, ScheduleCard.session)
        .all()
    )
    surgeon_ids = sorted({card.surgeon_id for card in cards})
    surgeons = list({card.surgeon_id: card.surgeon for card in cards}.values())
    locations = db.query(Location).filter(Location.is_active == True).all()  # noqa: E712
    aprima_by_slot = _aprima_rows_by_slot(db, start, end, surgeons, locations)
    cases = (
        db.query(SurgicalCase)
        .filter(
            SurgicalCase.surgeon_id.in_(surgeon_ids),
            SurgicalCase.date >= start,
            SurgicalCase.date <= end,
            SurgicalCase.status != "cancelled",
        )
        .all()
        if surgeon_ids else []
    )
    clinic_rows = (
        db.query(ClinicSchedule)
        .filter(
            ClinicSchedule.surgeon_id.in_(surgeon_ids),
            ClinicSchedule.date >= start,
            ClinicSchedule.date <= end,
            ClinicSchedule.assignment_type != "off",
        )
        .all()
        if surgeon_ids else []
    )
    approved_days_off = (
        db.query(DayOff)
        .filter(
            DayOff.surgeon_id.in_(surgeon_ids),
            DayOff.status == "approved",
            DayOff.start_date <= end,
            DayOff.end_date >= start,
        )
        .all()
        if surgeon_ids else []
    )

    clinic_times = _clinic_times_by_day(clinic_rows)
    case_counts: dict[tuple[int, date, str, int], int] = defaultdict(int)
    case_keys: dict[tuple[int, date, str, int], set[tuple[str, str]]] = defaultdict(set)
    for row in cases:
        if row.location_id:
            case_key = (row.surgeon_id, row.date, _case_session(row, clinic_times), row.location_id)
            case_counts[case_key] += 1
            stamp = row.start_time.strftime("%H:%M") if row.start_time else ""
            case_keys[case_key].add((_normal(row.patient_name), stamp))
    visit_counts = _clinic_visit_counts(clinic_rows)
    visit_segments: dict[tuple[int, date, str, int], list[dict]] = defaultdict(list)
    visit_keys: dict[tuple[int, date, str, int], set[tuple[str, str]]] = defaultdict(set)
    for row in clinic_rows:
        if not row.location_id:
            continue
        for segment in parse_clinic_fax_visit_segments(row.notes or ""):
            clock = _parse_clock(segment.get("start"))
            if not clock:
                continue
            key = (row.surgeon_id, row.date, _session_for_time(clock), row.location_id)
            visit_segments[key].append(segment)
            visit_keys[key].add((_normal(segment.get("label")), clock.strftime("%H:%M")))
    off_rows: dict[tuple[int, date], list[DayOff]] = defaultdict(list)
    for row in approved_days_off:
        day = max(row.start_date, start)
        final_day = min(row.end_date, end)
        while day <= final_day:
            off_rows[(row.surgeon_id, day)].append(row)
            day = day.fromordinal(day.toordinal() + 1)

    grid: dict[int, dict[date, dict[str, dict]]] = defaultdict(lambda: defaultdict(dict))
    surgeons = {}
    for card in cards:
        surgeons[card.surgeon_id] = card.surgeon
        location = card.effective_location
        aprima_rows = aprima_by_slot.get((card.surgeon_id, card.date, card.session), [])
        aprima_locations = {row["location"].id: row["location"] for row in aprima_rows}
        current_key = (card.surgeon_id, card.date, card.session, card.effective_location_id)
        current_activity = case_counts.get(current_key, 0) + visit_counts.get(current_key, 0)
        if len(aprima_locations) == 1:
            aprima_location = next(iter(aprima_locations.values()))
            if not location or location.id == aprima_location.id or current_activity == 0:
                location = aprima_location
        is_off = card.effective_state == "off" or any(
            _session_is_off(row, card.date, card.session)
            for row in off_rows.get((card.surgeon_id, card.date), [])
        )
        is_hospital = bool(location and ((location.location_type or "").lower() in {"hospital", "or"} or (location.abbreviation or "").upper().endswith("-OR")))
        location_id = location.id if location else None
        count_key = (card.surgeon_id, card.date, card.session, location_id)
        roster_visits = list(visit_segments.get(count_key, []))
        roster_aprima_cases: list[dict] = []
        for row in aprima_rows:
            if row["location"].id != location_id:
                continue
            dedupe_key = (row["patient_key"], row["start"])
            if row["is_surgery"] or is_hospital:
                if dedupe_key in case_keys[count_key]:
                    continue
                case_keys[count_key].add(dedupe_key)
                case_counts[count_key] += 1
                roster_aprima_cases.append(row)
                continue
            if dedupe_key in visit_keys[count_key]:
                continue
            visit_keys[count_key].add(dedupe_key)
            visit_counts[count_key] += 1
            roster_visits.append({
                "start": row["start"],
                "caseCount": 1,
                "note": row["label"],
                "label": row["label"],
                "source": "aprima",
            })
        roster_visits.sort(key=lambda row: (row.get("start") or "", row.get("label") or ""))
        count = case_counts.get(count_key, 0) if is_hospital else visit_counts.get(count_key, 0)
        unit = "case" if is_hospital else "visit"
        if not location:
            label = "NA"
            count_label = ""
        else:
            label = location.abbreviation or location.name
            count_label = f"{count} {unit if count == 1 else unit + 's'}"
        grid[card.surgeon_id][card.date][card.session] = {
            "card_id": card.id,
            "session": card.session,
            "label": label,
            "count_label": count_label,
            "is_off": is_off,
            "is_na": not location,
            "location_id": location_id,
            "location_color": location.color if location else "#e2e8f0",
            "location_type": "hospital" if is_hospital else "clinic",
            "roster_visits": roster_visits,
            "roster_aprima_cases": roster_aprima_cases,
            "has_aprima": bool(aprima_rows),
        }
    return {"grid": grid, "surgeons": list(surgeons.values())}
