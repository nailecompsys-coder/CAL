"""Read-only SQL projection of permanent schedule cards for the admin calendar."""

from __future__ import annotations

from collections import defaultdict
from datetime import date

from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from .models import DayOff, DayOffScheduleCard, Location, ScheduleCard, ScheduleCardActivity
from .schedule_activity_query_service import activity_counts_by_card


def _activity_rows_by_card(db: Session, start: date, end: date) -> dict[int, list[dict]]:
    result: dict[int, list[dict]] = defaultdict(list)
    canonical_ids = (
        db.query(func.min(ScheduleCardActivity.id).label("id"))
        .filter(
            ScheduleCardActivity.activity_date >= start,
            ScheduleCardActivity.activity_date <= end,
            ScheduleCardActivity.is_active == True,  # noqa: E712
        )
        .group_by(ScheduleCardActivity.schedule_card_id, ScheduleCardActivity.identity_key)
        .subquery()
    )
    rows = (
        db.query(ScheduleCardActivity)
        .join(canonical_ids, canonical_ids.c.id == ScheduleCardActivity.id)
        .options(joinedload(ScheduleCardActivity.location), joinedload(ScheduleCardActivity.surgeon))
        .filter(
            ScheduleCardActivity.activity_date >= start,
            ScheduleCardActivity.activity_date <= end,
            ScheduleCardActivity.is_active == True,  # noqa: E712
        )
        .order_by(ScheduleCardActivity.start_time, ScheduleCardActivity.id)
        .all()
    )
    for row in rows:
        result[row.schedule_card_id].append({
            "start": row.start_time.strftime("%H:%M") if row.start_time else "",
            "label": row.patient_name,
            "patient_key": row.identity_key,
            "location": row.location,
            "is_surgery": row.activity_type == "surgical",
            "room": row.room_text or "",
            "source": row.source_system,
            "surgeon": row.surgeon.full_name if row.surgeon else "",
            "surgeon_initials": row.surgeon.initials if row.surgeon else "",
        })
    return result


def _or_totals_by_day_location_sql(db: Session, start: date, end: date) -> dict[tuple[date, int], int]:
    rows = (
        db.query(
            ScheduleCardActivity.activity_date,
            ScheduleCardActivity.location_id,
            func.count(func.distinct(ScheduleCardActivity.identity_key)),
        )
        .filter(
            ScheduleCardActivity.activity_date >= start,
            ScheduleCardActivity.activity_date <= end,
            ScheduleCardActivity.activity_type == "surgical",
            ScheduleCardActivity.is_active == True,  # noqa: E712
            ScheduleCardActivity.location_id.isnot(None),
        )
        .group_by(ScheduleCardActivity.activity_date, ScheduleCardActivity.location_id)
        .all()
    )
    return {(day, location_id): int(total) for day, location_id, total in rows}


def card_grid_page_data(db: Session, start: date, end: date) -> dict:
    """Return permanent AM/PM cards and normalized relational detail. Never writes."""
    cards = (
        db.query(ScheduleCard)
        .options(joinedload(ScheduleCard.surgeon), joinedload(ScheduleCard.effective_location))
        .filter(ScheduleCard.date >= start, ScheduleCard.date <= end)
        .order_by(ScheduleCard.surgeon_id, ScheduleCard.date, ScheduleCard.session)
        .all()
    )
    locations = db.query(Location).filter(Location.is_active == True).all()  # noqa: E712
    activities_by_card = _activity_rows_by_card(db, start, end)
    activity_counts = activity_counts_by_card(db, start, end)
    or_totals = _or_totals_by_day_location_sql(db, start, end)

    card_ids = [card.id for card in cards]
    off_card_ids = {
        card_id for (card_id,) in (
            db.query(DayOffScheduleCard.schedule_card_id)
            .join(DayOff, DayOff.id == DayOffScheduleCard.day_off_id)
            .filter(
                DayOff.status == "approved",
                DayOffScheduleCard.schedule_card_id.in_(card_ids),
            )
            .all()
        )
    } if card_ids else set()

    grid: dict[int, dict[date, dict[str, dict]]] = defaultdict(lambda: defaultdict(dict))
    surgeons = {}
    for card in cards:
        surgeons[card.surgeon_id] = card.surgeon
        location = card.effective_location
        activity_rows = activities_by_card.get(card.id, [])
        activity_locations = {
            row["location"].id: row["location"] for row in activity_rows if row.get("location")
        }
        if len(activity_locations) == 1:
            row_location = next(iter(activity_locations.values()))
            if not location or location.id == row_location.id:
                location = row_location

        is_off = card.effective_state == "off" or card.id in off_card_ids
        is_hospital = bool(
            location and (
                (location.location_type or "").lower() in {"hospital", "or"}
                or (location.abbreviation or "").upper().endswith("-OR")
            )
        )
        roster_visits = [
            {
                "start": row["start"],
                "caseCount": 1,
                "note": row["label"],
                "label": row["label"],
                "source": row["source"],
            }
            for row in activity_rows if not row["is_surgery"]
        ]
        roster_cases = [row for row in activity_rows if row["is_surgery"]]
        unit = "case" if is_hospital else "visit"
        activity_type = "surgical" if is_hospital else "clinic"
        count = activity_counts.get((card.id, activity_type), 0)
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
            "count": count,
            "is_off": is_off,
            "is_na": not location,
            "location_id": location.id if location else None,
            "location_color": location.color if location else "#e2e8f0",
            "location_type": "hospital" if is_hospital else "clinic",
            "roster_visits": roster_visits,
            "roster_cases": roster_cases,
            "has_aprima": any(row["source"] == "aprima" for row in activity_rows),
        }

    hospital_locations = sorted(
        [
            location for location in locations
            if (location.location_type or "").lower() in {"hospital", "or"}
            or (location.abbreviation or "").upper().endswith("-OR")
        ],
        key=lambda row: (row.abbreviation or row.name),
    )
    hospital_headers: dict[date, list[dict]] = {}
    for ordinal in range(start.toordinal(), end.toordinal() + 1):
        day = date.fromordinal(ordinal)
        slots = []
        for location in hospital_locations:
            matching_cards = [
                sessions[session]
                for by_day in grid.values()
                for sessions in [by_day.get(day, {})]
                for session in ("am", "pm")
                if session in sessions and sessions[session].get("location_id") == location.id
            ]
            slots.append({
                "location_id": location.id,
                "label": location.abbreviation or location.name,
                "location_color": location.color or "#e2e8f0",
                "count": or_totals.get((day, location.id), 0),
                "roster_cases": [
                    case for card in matching_cards for case in card.get("roster_cases", [])
                ],
            })
        hospital_headers[day] = slots
    return {"grid": grid, "surgeons": list(surgeons.values()), "hospital_headers": hospital_headers}
