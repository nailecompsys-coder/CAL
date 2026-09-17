"""Read-only projection of permanent schedule cards for the admin calendar."""

from __future__ import annotations

from collections import defaultdict
from datetime import date, time

from sqlalchemy.orm import Session, joinedload

from .admin_clinic_schedule_page_service import parse_clinic_fax_visit_segments
from .models import ClinicSchedule, DayOff, ScheduleCard, SurgicalCase
from .native_dayoff_support import segment_for_date


def _session_for_time(value: time | None) -> str:
    return "pm" if value and value >= time(12, 0) else "am"


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

    case_counts: dict[tuple[int, date, str, int], int] = defaultdict(int)
    for row in cases:
        if row.location_id:
            case_counts[(row.surgeon_id, row.date, _session_for_time(row.start_time), row.location_id)] += 1
    visit_counts = _clinic_visit_counts(clinic_rows)
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
        is_off = card.effective_state == "off" or any(
            _session_is_off(row, card.date, card.session)
            for row in off_rows.get((card.surgeon_id, card.date), [])
        )
        is_hospital = bool(location and ((location.location_type or "").lower() in {"hospital", "or"} or (location.abbreviation or "").upper().endswith("-OR")))
        count_key = (card.surgeon_id, card.date, card.session, card.effective_location_id)
        count = case_counts.get(count_key, 0) if is_hospital else visit_counts.get(count_key, 0)
        unit = "case" if is_hospital else "visit"
        if card.effective_state == "na" or not location:
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
            "is_na": card.effective_state == "na" or not location,
            "location_color": location.color if location else "#e2e8f0",
            "location_type": "hospital" if is_hospital else "clinic",
        }
    return {"grid": grid, "surgeons": list(surgeons.values())}
