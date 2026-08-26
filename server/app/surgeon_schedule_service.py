"""Build surgeon schedule view models."""
from datetime import date, timedelta

from sqlalchemy.orm import Session

from .call_schedule_utils import (
    build_call_group_rows,
    build_call_rail_slots,
    index_rotations_by_group_date,
    serialize_call_group_rail,
)
from .surgeon_schedule_queries import (
    call_groups as query_call_groups,
    off_surgeons_by_day,
    personal_items_by_day,
    practice_rotations_by_range,
    surgeon_approved_off_by_day,
    surgeon_clinics_by_day,
    surgeon_meetings_by_day,
    surgeon_rotations_by_day,
    surgeon_surgeries_by_day,
)
from .surgeon_schedule_serializers import serialize_schedule_week
from .surgeon_schedule_slots import compute_schedule_slots
from .practice_time import practice_today


def _merge_aprima_surgeries(db: Session, surgeon, surgeries_by_day: dict, start_day: date, end_day: date) -> None:
    """Append Aprima Surgery appointments into the surgeon schedule surgery buckets."""
    from types import SimpleNamespace
    from datetime import time as time_cls

    from .aprima_cache_service import patient_appointments_for_api
    from .aprima_schedule_service import is_surgery_appointment

    def _hhmm(value: str | None):
        raw = (value or "").strip()
        if not raw or ":" not in raw:
            return None
        try:
            hour_s, minute_s = raw.split(":", 1)
            return time_cls(int(hour_s), int(minute_s))
        except ValueError:
            return None

    payload = patient_appointments_for_api(db, start_day, end_day, surgeon=surgeon)
    for row in payload.get("appointments") or []:
        if not is_surgery_appointment(row):
            continue
        day_key = (row.get("date") or "").strip()
        try:
            day = date.fromisoformat(day_key)
        except ValueError:
            continue
        if day < start_day or day > end_day:
            continue
        appt_id = str(row.get("id") or "")
        surgeries_by_day.setdefault(day, []).append(
            SimpleNamespace(
                id=f"aprima-{appt_id}",
                start_time=_hhmm(row.get("start")) or time_cls(8, 0),
                end_time=_hhmm(row.get("end")),
                patient_name=(row.get("patientName") or "").strip(),
                procedure=(row.get("reason") or row.get("appointmentType") or "Surgery").strip(),
                location=None,
                room_text=(row.get("room") or row.get("serviceSite") or "").strip(),
                status=(row.get("status") or "scheduled").strip().lower(),
                surgeon_notes="",
                source="aprima",
            )
        )


def build_surgeon_schedule_view(db: Session, surgeon, week_offset: int = 0) -> dict:
    today = practice_today()
    week_start = today - timedelta(days=today.weekday()) + timedelta(weeks=week_offset)
    week_days = [week_start + timedelta(days=i) for i in range(7)]
    week_end = week_days[-1]
    summary_start = min(week_start, today)
    summary_end = max(week_end, today)

    call_groups = query_call_groups(db)
    call_group_rows = build_call_group_rows(call_groups)
    practice_rotations = practice_rotations_by_range(db, week_days[0], week_end)
    call_rotation_index = index_rotations_by_group_date(practice_rotations, call_groups)

    rotations_by_day = surgeon_rotations_by_day(db, surgeon.id, summary_start, summary_end)
    meetings_by_day = surgeon_meetings_by_day(db, surgeon.id, summary_start, summary_end)
    clinics_by_day = surgeon_clinics_by_day(db, surgeon.id, summary_start, summary_end)
    surgeries_by_day = surgeon_surgeries_by_day(db, surgeon.id, summary_start, summary_end)
    _merge_aprima_surgeries(db, surgeon, surgeries_by_day, summary_start, summary_end)
    my_off_by_day = surgeon_approved_off_by_day(db, surgeon.id, summary_start, summary_end)

    week_summary = []
    for day in week_days:
        week_summary.append({
            "date": day,
            "rotations": rotations_by_day.get(day, []),
            "day_off": my_off_by_day.get(day),
            "meetings": meetings_by_day.get(day, []),
            "clinics": clinics_by_day.get(day, []),
            "surgeries": surgeries_by_day.get(day, []),
        })

    off_by_day = off_surgeons_by_day(db, week_days[0], week_end)
    personal_by_day = personal_items_by_day(db, surgeon.id, week_days[0], week_end)

    for ws in week_summary:
        d = ws["date"]
        off_map = off_by_day.get(d, {})
        ws["off_surgeons"] = sorted(
            off_map.values(),
            key=lambda s: ((s.last_name or "").lower(), (s.first_name or "").lower()),
        )
        ws["personal_items"] = personal_by_day.get(d, [])
        ws["slots"] = compute_schedule_slots(ws)
        ws["call_rail_slots"] = build_call_rail_slots(call_group_rows, call_rotation_index, d)
        ws["serialized_call_rail"] = serialize_call_group_rail(ws["call_rail_slots"])

    today_bucket = next((ws for ws in week_summary if ws["date"] == today), None)
    if not today_bucket:
        today_bucket = {
            "date": today,
            "rotations": rotations_by_day.get(today, []),
            "day_off": my_off_by_day.get(today),
            "meetings": meetings_by_day.get(today, []),
            "clinics": clinics_by_day.get(today, []),
            "surgeries": surgeries_by_day.get(today, []),
        }
    today_summary = {
        "date": today,
        "rotations": today_bucket["rotations"],
        "day_off": today_bucket["day_off"],
        "meetings": today_bucket["meetings"],
        "clinics": today_bucket["clinics"],
        "surgeries": today_bucket["surgeries"],
    }

    week_json = serialize_schedule_week(week_summary, surgeon.id)

    return {
        "week_days": week_days,
        "week_summary": week_summary,
        "call_groups": call_groups,
        "today_summary": today_summary,
        "week_offset": week_offset,
        "week_json": week_json,
    }
