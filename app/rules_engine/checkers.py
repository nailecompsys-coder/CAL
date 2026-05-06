"""Rule checker functions. Each yields zero or more Conflict objects."""
from datetime import date, time, datetime, timedelta
from typing import Any, Iterator, Optional

from sqlalchemy.orm import Session
from sqlalchemy import or_

from .registry import CLINIC_AM_END, CLINIC_PM_END, CLINIC_PM_START, Conflict, _session_end_time, _session_start_time


def _exclude_entity(
    exclude_entity: Optional[tuple[str, int]],
    entity_type: str,
    entity_id: int,
) -> bool:
    """True if this entity should be excluded from conflict check (e.g. the one being saved)."""
    if not exclude_entity:
        return False
    etype, eid = exclude_entity
    return etype == entity_type and eid == entity_id


def _target_type(target_entity: Optional[dict]) -> Optional[str]:
    return (target_entity or {}).get("type")


def _target_dates(target_entity: Optional[dict], start_date: date, end_date: date) -> tuple[date, date]:
    if not target_entity:
        return start_date, end_date
    return (
        target_entity.get("start_date", target_entity.get("date", start_date)),
        target_entity.get("end_date", target_entity.get("date", end_date)),
    )


def _session_range(d: date, session: str | None) -> tuple[datetime, datetime]:
    normalized = (session or "full").lower()
    return (
        datetime.combine(d, _session_start_time(normalized)),
        datetime.combine(d, _session_end_time(normalized)),
    )


def _case_range(sc) -> tuple[datetime, datetime]:
    start_dt = datetime.combine(sc.date, sc.start_time)
    end_dt = datetime.combine(sc.date, sc.end_time) if sc.end_time else start_dt + timedelta(hours=1)
    return start_dt, end_dt


def _meeting_range(m) -> tuple[datetime, datetime]:
    if m.start_time is None:
        start_dt = datetime.combine(m.date, time(0, 0))
        return start_dt, start_dt + timedelta(days=1)
    start_dt = datetime.combine(m.date, m.start_time)
    end_dt = datetime.combine(m.date, m.end_time) if m.end_time else start_dt + timedelta(hours=1)
    return start_dt, end_dt


def _target_range_on_day(target_entity: Optional[dict], day: date) -> Optional[tuple[datetime, datetime]]:
    if not target_entity:
        return None
    ttype = _target_type(target_entity)
    if ttype == "clinic_schedule":
        return _session_range(day, target_entity.get("session"))
    if ttype == "surgical_case":
        start_t = target_entity.get("start_time")
        if not start_t:
            return None
        start_dt = datetime.combine(day, start_t)
        end_t = target_entity.get("end_time")
        end_dt = datetime.combine(day, end_t) if end_t else start_dt + timedelta(hours=1)
        return start_dt, end_dt
    if ttype == "meeting":
        start_t = target_entity.get("start_time")
        if start_t is None:
            start_dt = datetime.combine(day, time(0, 0))
            return start_dt, start_dt + timedelta(days=1)
        start_dt = datetime.combine(day, start_t)
        end_t = target_entity.get("end_time")
        end_dt = datetime.combine(day, end_t) if end_t else start_dt + timedelta(hours=1)
        return start_dt, end_dt
    return None


def _ranges_overlap(a_start: datetime, a_end: datetime, b_start: datetime, b_end: datetime) -> bool:
    return a_start < b_end and b_start < a_end


# ─── Overlap rules ───────────────────────────────────────────────────────────

def check_overlap_day_off(
    surgeon_id: int,
    start_date: date,
    end_date: date,
    db: Session,
    config: dict,
    exclude_entity: Optional[tuple[str, int]] = None,
    target_entity: Optional[dict] = None,
) -> Iterator[Conflict]:
    from ..models import DayOff
    target_start, target_end = _target_dates(target_entity, start_date, end_date)
    q = db.query(DayOff).filter(
        DayOff.surgeon_id == surgeon_id,
        DayOff.start_date <= target_end,
        DayOff.end_date >= target_start,
        DayOff.status == "approved",
    )
    if exclude_entity and exclude_entity[0] == "day_off":
        q = q.filter(DayOff.id != exclude_entity[1])
    for d in q.all():
        for d_ in range((min(d.end_date, end_date) - max(d.start_date, start_date)).days + 1):
            day = max(d.start_date, start_date) + timedelta(days=d_)
            msg = f"Approved day off on {day.strftime('%b %-d')}"
            yield Conflict(
                rule_id="OVERLAP_DAY_OFF",
                surgeon_id=surgeon_id,
                date=day,
                message=msg,
                conflicting_entity_type="day_off",
                conflicting_entity_id=d.id,
            )


def check_overlap_call(
    surgeon_id: int,
    start_date: date,
    end_date: date,
    db: Session,
    config: dict,
    exclude_entity: Optional[tuple[str, int]] = None,
    target_entity: Optional[dict] = None,
) -> Iterator[Conflict]:
    from ..models import CallRotation
    target_start, target_end = _target_dates(target_entity, start_date, end_date)
    for r in db.query(CallRotation).filter(
        CallRotation.surgeon_id == surgeon_id,
        CallRotation.date >= target_start,
        CallRotation.date <= target_end,
    ).all():
        if _exclude_entity(exclude_entity, "call_rotation", r.id):
            continue
        label = "on-call"
        yield Conflict(
            rule_id="OVERLAP_CALL",
            surgeon_id=surgeon_id,
            date=r.date,
            message=f"Assigned {label} on {r.date.strftime('%b %-d')}",
            conflicting_entity_type="call_rotation",
            conflicting_entity_id=r.id,
        )


def check_overlap_unavailable(
    surgeon_id: int,
    start_date: date,
    end_date: date,
    db: Session,
    config: dict,
    exclude_entity: Optional[tuple[str, int]] = None,
    target_entity: Optional[dict] = None,
) -> Iterator[Conflict]:
    from ..models import Availability
    target_start, target_end = _target_dates(target_entity, start_date, end_date)
    for av in db.query(Availability).filter(
        Availability.surgeon_id == surgeon_id,
        Availability.date >= target_start,
        Availability.date <= target_end,
        Availability.is_available == False,
    ).all():
        yield Conflict(
            rule_id="OVERLAP_UNAVAILABLE",
            surgeon_id=surgeon_id,
            date=av.date,
            message=f"Marked unavailable on {av.date.strftime('%b %-d')}",
            conflicting_entity_type="availability",
            conflicting_entity_id=av.id,
        )


def check_overlap_clinic(
    surgeon_id: int,
    start_date: date,
    end_date: date,
    db: Session,
    config: dict,
    exclude_entity: Optional[tuple[str, int]] = None,
    target_entity: Optional[dict] = None,
) -> Iterator[Conflict]:
    from ..models import ClinicSchedule
    target_type = _target_type(target_entity)
    target_start, target_end = _target_dates(target_entity, start_date, end_date)
    target_day = target_entity.get("date") if target_entity else None
    target_range = _target_range_on_day(target_entity, target_day) if target_day else None
    for cs in db.query(ClinicSchedule).filter(
        ClinicSchedule.surgeon_id == surgeon_id,
        ClinicSchedule.date >= target_start,
        ClinicSchedule.date <= target_end,
    ).all():
        if _exclude_entity(exclude_entity, "clinic_schedule", cs.id):
            continue
        if target_type in {"clinic_schedule", "surgical_case", "meeting"}:
            if not target_day or cs.date != target_day or not target_range:
                continue
            clinic_start, clinic_end = _session_range(cs.date, cs.session)
            if not _ranges_overlap(clinic_start, clinic_end, target_range[0], target_range[1]):
                continue
        loc_name = cs.location.name if cs.location else "Clinic"
        yield Conflict(
            rule_id="OVERLAP_CLINIC",
            surgeon_id=surgeon_id,
            date=cs.date,
            message=f"Clinic at {loc_name} on {cs.date.strftime('%b %-d')} ({cs.session})",
            conflicting_entity_type="clinic_schedule",
            conflicting_entity_id=cs.id,
        )


def check_overlap_surgery(
    surgeon_id: int,
    start_date: date,
    end_date: date,
    db: Session,
    config: dict,
    exclude_entity: Optional[tuple[str, int]] = None,
    target_entity: Optional[dict] = None,
) -> Iterator[Conflict]:
    from ..models import SurgicalCase
    target_type = _target_type(target_entity)
    target_start, target_end = _target_dates(target_entity, start_date, end_date)
    target_day = target_entity.get("date") if target_entity else None
    target_range = _target_range_on_day(target_entity, target_day) if target_day else None
    q = db.query(SurgicalCase).filter(
        SurgicalCase.surgeon_id == surgeon_id,
        SurgicalCase.date >= target_start,
        SurgicalCase.date <= target_end,
        SurgicalCase.status != "cancelled",
    )
    if exclude_entity and exclude_entity[0] == "surgical_case":
        q = q.filter(SurgicalCase.id != exclude_entity[1])
    for sc in q.all():
        if target_type in {"surgical_case", "clinic_schedule", "meeting"}:
            if not target_day or sc.date != target_day or not target_range:
                continue
            case_start, case_end = _case_range(sc)
            if not _ranges_overlap(case_start, case_end, target_range[0], target_range[1]):
                continue
        yield Conflict(
            rule_id="OVERLAP_SURGERY",
            surgeon_id=surgeon_id,
            date=sc.date,
            message=f"Surgery on {sc.date.strftime('%b %-d')} ({sc.start_time.strftime('%-I:%M %p')} — {sc.patient_name or 'case'})",
            conflicting_entity_type="surgical_case",
            conflicting_entity_id=sc.id,
        )


def check_overlap_meeting(
    surgeon_id: int,
    start_date: date,
    end_date: date,
    db: Session,
    config: dict,
    exclude_entity: Optional[tuple[str, int]] = None,
    target_entity: Optional[dict] = None,
) -> Iterator[Conflict]:
    from ..models import Meeting, MeetingAttendee
    target_type = _target_type(target_entity)
    target_start, target_end = _target_dates(target_entity, start_date, end_date)
    target_day = target_entity.get("date") if target_entity else None
    target_range = _target_range_on_day(target_entity, target_day) if target_day else None
    meetings = (
        db.query(Meeting)
        .outerjoin(MeetingAttendee)
        .filter(
            Meeting.date >= target_start,
            Meeting.date <= target_end,
            or_(
                MeetingAttendee.surgeon_id == surgeon_id,
                ~Meeting.attendees.any(),
            ),
        )
        .distinct()
        .all()
    )
    for m in meetings:
        if _exclude_entity(exclude_entity, "meeting", m.id):
            continue
        if target_type in {"meeting", "clinic_schedule", "surgical_case"}:
            if not target_day or m.date != target_day or not target_range:
                continue
            meeting_start, meeting_end = _meeting_range(m)
            if not _ranges_overlap(meeting_start, meeting_end, target_range[0], target_range[1]):
                continue
        time_str = m.start_time.strftime("%-I:%M %p") if m.start_time else "TBD"
        yield Conflict(
            rule_id="OVERLAP_MEETING",
            surgeon_id=surgeon_id,
            date=m.date,
            message=f"Meeting: {m.title} on {m.date.strftime('%b %-d')} at {time_str}",
            conflicting_entity_type="meeting",
            conflicting_entity_id=m.id,
        )


# ─── Buffer rules (time between events) ──────────────────────────────────────

def _parse_time(t: Optional[time]) -> Optional[datetime]:
    if t is None:
        return None
    return datetime.combine(date.today(), t)


def check_buffer_clinic_to_surgery(
    surgeon_id: int,
    start_date: date,
    end_date: date,
    db: Session,
    config: dict,
    exclude_entity: Optional[tuple[str, int]] = None,
    target_entity: Optional[dict] = None,
) -> Iterator[Conflict]:
    from ..models import ClinicSchedule, SurgicalCase
    if _target_type(target_entity) not in {"clinic_schedule", "surgical_case"}:
        return
    minutes = config.get("minutes", 30)
    delta = timedelta(minutes=minutes)
    clinics = db.query(ClinicSchedule).filter(
        ClinicSchedule.surgeon_id == surgeon_id,
        ClinicSchedule.date >= start_date,
        ClinicSchedule.date <= end_date,
    ).all()
    surgeries = db.query(SurgicalCase).filter(
        SurgicalCase.surgeon_id == surgeon_id,
        SurgicalCase.date >= start_date,
        SurgicalCase.date <= end_date,
        SurgicalCase.status != "cancelled",
    )
    if exclude_entity and exclude_entity[0] == "surgical_case":
        surgeries = surgeries.filter(SurgicalCase.id != exclude_entity[1])
    surgeries = surgeries.all()
    for sc in surgeries:
        case_start = datetime.combine(sc.date, sc.start_time)
        for cs in clinics:
            if cs.date != sc.date:
                continue
            end_t = _session_end_time(cs.session or "full")
            clinic_end = datetime.combine(cs.date, end_t)
            if clinic_end <= case_start and (case_start - clinic_end) < delta:
                yield Conflict(
                    rule_id="BUFFER_CLINIC_TO_SURGERY",
                    surgeon_id=surgeon_id,
                    date=sc.date,
                    message=f"Clinic then surgery: need {minutes} min between clinic end and surgery start (case: {sc.patient_name or 'surgery'})",
                    severity="warning",
                    conflicting_entity_type="surgical_case",
                    conflicting_entity_id=sc.id,
                )


def check_buffer_surgery_to_clinic(
    surgeon_id: int,
    start_date: date,
    end_date: date,
    db: Session,
    config: dict,
    exclude_entity: Optional[tuple[str, int]] = None,
    target_entity: Optional[dict] = None,
) -> Iterator[Conflict]:
    from ..models import ClinicSchedule, SurgicalCase
    if _target_type(target_entity) not in {"clinic_schedule", "surgical_case"}:
        return
    minutes = config.get("minutes", 30)
    delta = timedelta(minutes=minutes)
    clinics = db.query(ClinicSchedule).filter(
        ClinicSchedule.surgeon_id == surgeon_id,
        ClinicSchedule.date >= start_date,
        ClinicSchedule.date <= end_date,
    ).all()
    surgeries = db.query(SurgicalCase).filter(
        SurgicalCase.surgeon_id == surgeon_id,
        SurgicalCase.date >= start_date,
        SurgicalCase.date <= end_date,
        SurgicalCase.status != "cancelled",
    )
    if exclude_entity and exclude_entity[0] == "surgical_case":
        surgeries = surgeries.filter(SurgicalCase.id != exclude_entity[1])
    surgeries = surgeries.all()
    for cs in clinics:
        clinic_start = datetime.combine(cs.date, _session_start_time(cs.session or "full"))
        for sc in surgeries:
            if sc.date != cs.date:
                continue
            case_end = datetime.combine(sc.date, sc.end_time) if sc.end_time else datetime.combine(sc.date, sc.start_time) + timedelta(hours=1)
            if case_end <= clinic_start and (clinic_start - case_end) < delta:
                yield Conflict(
                    rule_id="BUFFER_SURGERY_TO_CLINIC",
                    surgeon_id=surgeon_id,
                    date=cs.date,
                    message=f"Surgery then clinic: need {minutes} min between last surgery and clinic start ({cs.location.name if cs.location else 'clinic'})",
                    severity="warning",
                    conflicting_entity_type="clinic_schedule",
                    conflicting_entity_id=cs.id,
                )


def check_buffer_between_cases(
    surgeon_id: int,
    start_date: date,
    end_date: date,
    db: Session,
    config: dict,
    exclude_entity: Optional[tuple[str, int]] = None,
    target_entity: Optional[dict] = None,
) -> Iterator[Conflict]:
    from ..models import SurgicalCase
    if _target_type(target_entity) != "surgical_case":
        return
    minutes = config.get("minutes", 15)
    delta = timedelta(minutes=minutes)
    q = db.query(SurgicalCase).filter(
        SurgicalCase.surgeon_id == surgeon_id,
        SurgicalCase.date >= start_date,
        SurgicalCase.date <= end_date,
        SurgicalCase.status != "cancelled",
    ).order_by(SurgicalCase.date, SurgicalCase.start_time)
    if exclude_entity and exclude_entity[0] == "surgical_case":
        q = q.filter(SurgicalCase.id != exclude_entity[1])
    cases = q.all()
    for i in range(len(cases) - 1):
        a, b = cases[i], cases[i + 1]
        if a.date != b.date:
            continue
        end_a = datetime.combine(a.date, a.end_time) if a.end_time else datetime.combine(a.date, a.start_time) + timedelta(hours=1)
        start_b = datetime.combine(b.date, b.start_time)
        if end_a <= start_b and (start_b - end_a) < delta:
            yield Conflict(
                rule_id="BUFFER_BETWEEN_CASES",
                surgeon_id=surgeon_id,
                date=a.date,
                message=f"Turn time: need {minutes} min between cases ({a.patient_name or 'case'} → {b.patient_name or 'case'})",
                severity="warning",
                conflicting_entity_type="surgical_case",
                conflicting_entity_id=b.id,
            )


def check_buffer_same_site_am_pm(
    surgeon_id: int,
    start_date: date,
    end_date: date,
    db: Session,
    config: dict,
    exclude_entity: Optional[tuple[str, int]] = None,
    target_entity: Optional[dict] = None,
) -> Iterator[Conflict]:
    from ..models import ClinicSchedule, SurgicalCase
    if _target_type(target_entity) not in {"clinic_schedule", "surgical_case"}:
        return
    minutes = config.get("minutes", 30)
    delta = timedelta(minutes=minutes)
    clinics = db.query(ClinicSchedule).filter(
        ClinicSchedule.surgeon_id == surgeon_id,
        ClinicSchedule.date >= start_date,
        ClinicSchedule.date <= end_date,
    ).all()
    surgeries = db.query(SurgicalCase).filter(
        SurgicalCase.surgeon_id == surgeon_id,
        SurgicalCase.date >= start_date,
        SurgicalCase.date <= end_date,
        SurgicalCase.status != "cancelled",
    )
    if exclude_entity and exclude_entity[0] == "surgical_case":
        surgeries = surgeries.filter(SurgicalCase.id != exclude_entity[1])
    surgeries = surgeries.all()
    for cs in clinics:
        if (cs.session or "").lower() != "am":
            continue
        for sc in surgeries:
            if sc.date != cs.date or not sc.location_id or not cs.location_id:
                continue
            if sc.location_id != cs.location_id:
                continue
            clinic_end = datetime.combine(cs.date, CLINIC_AM_END)
            case_start = datetime.combine(sc.date, sc.start_time)
            if case_start > clinic_end and (case_start - clinic_end) < delta:
                yield Conflict(
                    rule_id="BUFFER_SAME_SITE_AM_PM",
                    surgeon_id=surgeon_id,
                    date=cs.date,
                    message=f"Same site AM clinic → PM surgery: need {minutes} min gap at {cs.location.name if cs.location else 'same site'}",
                    severity="warning",
                    conflicting_entity_type="surgical_case",
                    conflicting_entity_id=sc.id,
                )


def check_location_drive_time(
    surgeon_id: int,
    start_date: date,
    end_date: date,
    db: Session,
    config: dict,
    exclude_entity: Optional[tuple[str, int]] = None,
    target_entity: Optional[dict] = None,
) -> Iterator[Conflict]:
    from ..models import ClinicSchedule, SurgicalCase
    if _target_type(target_entity) not in {"clinic_schedule", "surgical_case"}:
        return
    minutes = config.get("minutes_between_sites", 60)
    delta = timedelta(minutes=minutes)
    clinics = db.query(ClinicSchedule).filter(
        ClinicSchedule.surgeon_id == surgeon_id,
        ClinicSchedule.date >= start_date,
        ClinicSchedule.date <= end_date,
    ).all()
    surgeries = db.query(SurgicalCase).filter(
        SurgicalCase.surgeon_id == surgeon_id,
        SurgicalCase.date >= start_date,
        SurgicalCase.date <= end_date,
        SurgicalCase.status != "cancelled",
    )
    if exclude_entity and exclude_entity[0] == "surgical_case":
        surgeries = surgeries.filter(SurgicalCase.id != exclude_entity[1])
    surgeries = surgeries.all()
    for cs in clinics:
        for sc in surgeries:
            if sc.date != cs.date or not sc.location_id or not cs.location_id:
                continue
            if sc.location_id == cs.location_id:
                continue
            clinic_end = datetime.combine(cs.date, _session_end_time(cs.session or "full"))
            case_start = datetime.combine(sc.date, sc.start_time)
            if case_start > clinic_end and (case_start - clinic_end) < delta:
                yield Conflict(
                    rule_id="LOCATION_DRIVE_TIME",
                    surgeon_id=surgeon_id,
                    date=sc.date,
                    message=f"Different sites same day: allow {minutes} min between clinic and surgery at different location",
                    severity="warning",
                    conflicting_entity_type="surgical_case",
                    conflicting_entity_id=sc.id,
                )
