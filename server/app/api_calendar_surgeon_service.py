"""Surgeon calendar API event builders."""

from datetime import timedelta

from sqlalchemy.orm import Session, joinedload

from .api_calendar_utils import NEUTRAL_CAL_BG, NEUTRAL_CAL_TEXT, pastel_from_location_hex
from .models import CallRotation, ClinicSchedule, DayOff
from .native_support import meetings_for_surgeon


def build_surgeon_calendar_events(db: Session, surgeon, start_date, end_date) -> list[dict]:
    events = []

    rotations = db.query(CallRotation).filter(
        CallRotation.surgeon_id == surgeon.id,
        CallRotation.date >= start_date,
        CallRotation.date <= end_date,
    ).all()
    for rotation in rotations:
        events.append({
            "id": f"rot-{rotation.id}", "title": "🔔 On-Call",
            "start": rotation.date.isoformat(),
            "color": NEUTRAL_CAL_BG,
            "textColor": NEUTRAL_CAL_TEXT,
            "extendedProps": {"type": "oncall"},
        })

    daysoff = db.query(DayOff).filter(
        DayOff.surgeon_id == surgeon.id,
        DayOff.start_date <= end_date,
        DayOff.end_date >= start_date,
        DayOff.status == "approved",
    ).all()
    for day_off in daysoff:
        events.append({
            "id": f"off-{day_off.id}", "title": "🏖 Day Off",
            "start": day_off.start_date.isoformat(),
            "end": (day_off.end_date + timedelta(days=1)).isoformat(),
            "color": NEUTRAL_CAL_BG,
            "textColor": NEUTRAL_CAL_TEXT,
        })

    for meeting in meetings_for_surgeon(db, surgeon.id, start_date, end_date):
        start_dt = f"{meeting.date.isoformat()}T{meeting.start_time.isoformat()}" if meeting.start_time else meeting.date.isoformat()
        events.append({
            "id": f"mtg-{meeting.id}", "title": f"📋 {meeting.title}",
            "start": start_dt,
            "end": f"{meeting.date.isoformat()}T{meeting.end_time.isoformat()}" if meeting.end_time else None,
            "color": NEUTRAL_CAL_BG,
            "textColor": NEUTRAL_CAL_TEXT,
        })

    my_clinics = db.query(ClinicSchedule).options(
        joinedload(ClinicSchedule.location),
    ).filter(
        ClinicSchedule.surgeon_id == surgeon.id,
        ClinicSchedule.date >= start_date,
        ClinicSchedule.date <= end_date,
    ).all()
    for clinic_schedule in my_clinics:
        loc = clinic_schedule.location
        loc_hex = (loc.color or "#0ea5e9").strip() if loc else "#0ea5e9"
        time_slot = "T08:00:00" if clinic_schedule.session == "am" else "T13:00:00" if clinic_schedule.session == "pm" else "T08:00:00"
        loc_label = loc.name if loc else "Clinic"
        events.append({
            "id": f"clinic-{clinic_schedule.id}",
            "title": f"📍 {loc_label}",
            "start": f"{clinic_schedule.date.isoformat()}{time_slot}",
            "color": pastel_from_location_hex(loc_hex),
            "textColor": "#1e293b",
            "extendedProps": {"type": "clinic", "location": loc_label, "session": clinic_schedule.session},
        })

    return events
