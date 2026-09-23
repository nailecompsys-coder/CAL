"""Day-off vs clinic/OR workload: display OFF and flag Shannon conflicts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, time

from sqlalchemy import case, func
from sqlalchemy.orm import Session, joinedload

from .models import ClinicSchedule, DayOff, DayOffScheduleCard, ScheduleCard, ScheduleCardActivity, Surgeon
from .surgeon_visibility import surgeon_is_visible


AM_END = time(12, 0)
DAY_START = time(0, 0)
DAY_END = time(23, 59, 59)


@dataclass(frozen=True)
class OffWorkload:
    case_count: int = 0
    patient_count: int = 0

    @property
    def has_work(self) -> bool:
        return self.case_count > 0 or self.patient_count > 0


@dataclass(frozen=True)
class OffConflict:
    surgeon_id: int
    surgeon_initials: str
    surgeon_name: str
    day: date
    day_off_status: str  # approved | pending
    day_off_id: int
    case_count: int
    patient_count: int
    message: str

    def as_dict(self) -> dict:
        return {
            "surgeonId": self.surgeon_id,
            "surgeonInitials": self.surgeon_initials,
            "surgeonName": self.surgeon_name,
            "date": self.day.isoformat(),
            "dayOffStatus": self.day_off_status,
            "dayOffId": self.day_off_id,
            "caseCount": self.case_count,
            "patientCount": self.patient_count,
            "message": self.message,
        }


def day_off_status_map(
    db: Session,
    start_date: date,
    end_date: date,
) -> dict[tuple[int, date], dict]:
    """(surgeon_id, day) -> {status, day_off_id, reason}. Prefer approved over pending."""
    rows = (
        db.query(DayOff, ScheduleCard)
        .join(DayOffScheduleCard, DayOffScheduleCard.day_off_id == DayOff.id)
        .join(ScheduleCard, ScheduleCard.id == DayOffScheduleCard.schedule_card_id)
        .options(joinedload(DayOff.surgeon))
        .filter(
            ScheduleCard.date >= start_date,
            ScheduleCard.date <= end_date,
            DayOff.status.in_(("approved", "pending")),
        )
        .all()
    )
    out: dict[tuple[int, date], dict] = {}
    for row, card in rows:
        if not surgeon_is_visible(row.surgeon):
            continue
        key = (row.surgeon_id, card.date)
        existing = out.get(key)
        if existing and existing["status"] == "approved":
            existing["sessions"].add(card.session)
            continue
        if row.status == "approved" or not existing:
            out[key] = {
                "status": row.status,
                "day_off_id": row.id,
                "reason": row.reason,
                "surgeon": row.surgeon,
                "sessions": {card.session},
            }
    return out


def _parse_segment_time(value, fallback: time | None = None) -> time | None:
    if isinstance(value, time):
        return value
    if isinstance(value, str) and value:
        try:
            hour, minute = value.split(":", 1)
            return time(int(hour), int(minute[:2]))
        except (TypeError, ValueError):
            return fallback
    return fallback


def day_off_sessions(segment: dict | None) -> set[str]:
    """Return schedule sessions affected by a day-off segment."""
    if not segment or segment.get("isFullDay", True):
        return {"am", "pm"}
    start = _parse_segment_time(segment.get("start"), DAY_START)
    end = _parse_segment_time(segment.get("end"), DAY_END)
    if not start or not end or end <= start:
        return {"am", "pm"}
    sessions: set[str] = set()
    if start < AM_END and end > DAY_START:
        sessions.add("am")
    if end > AM_END:
        sessions.add("pm")
    return sessions or {"am", "pm"}


def schedule_matches_off_session(schedule: ClinicSchedule, off_info: dict | None) -> bool:
    if not off_info:
        return False
    sessions = set(off_info.get("sessions") or {"am", "pm"})
    schedule_session = (schedule.session or "full").lower()
    if schedule_session in {"full", "both"}:
        return bool(sessions)
    return schedule_session in sessions


def workload_maps(
    db: Session,
    start_date: date,
    end_date: date,
    *,
    sched_map: dict | None = None,
    surgical_map: dict | None = None,
    or_case_map: dict | None = None,
) -> dict[tuple[int, date], OffWorkload]:
    """Aggregate cases and visits with one SQL GROUP BY over normalized rows."""
    rows = (
        db.query(
            ScheduleCardActivity.surgeon_id,
            ScheduleCardActivity.activity_date,
            func.count(func.distinct(case(
                (ScheduleCardActivity.activity_type == "surgical", ScheduleCardActivity.identity_key),
                else_=None,
            ))).label("case_count"),
            func.count(func.distinct(case(
                (ScheduleCardActivity.activity_type == "clinic", ScheduleCardActivity.identity_key),
                else_=None,
            ))).label("patient_count"),
        )
        .filter(
            ScheduleCardActivity.activity_date >= start_date,
            ScheduleCardActivity.activity_date <= end_date,
            ScheduleCardActivity.is_active == True,  # noqa: E712
        )
        .group_by(ScheduleCardActivity.surgeon_id, ScheduleCardActivity.activity_date)
        .all()
    )
    return {
        (row.surgeon_id, row.activity_date): OffWorkload(
            case_count=int(row.case_count or 0),
            patient_count=int(row.patient_count or 0),
        )
        for row in rows
    }


def detect_off_conflicts(
    db: Session,
    start_date: date,
    end_date: date,
    *,
    sched_map: dict | None = None,
    surgical_map: dict | None = None,
    or_case_map: dict | None = None,
) -> list[OffConflict]:
    off_map = day_off_status_map(db, start_date, end_date)
    workloads = workload_maps(
        db, start_date, end_date,
        sched_map=sched_map,
        surgical_map=surgical_map,
        or_case_map=or_case_map,
    )
    conflicts: list[OffConflict] = []
    for (surgeon_id, day), off_info in sorted(off_map.items(), key=lambda item: (item[0][1], item[0][0])):
        load = workloads.get((surgeon_id, day), OffWorkload())
        if not load.has_work:
            continue
        surgeon = off_info.get("surgeon") or db.get(Surgeon, surgeon_id)
        if not surgeon_is_visible(surgeon):
            continue
        status = off_info["status"]
        status_label = "approved OFF" if status == "approved" else "requested OFF (pending)"
        parts = []
        if load.case_count:
            parts.append(f"{load.case_count} surgical case{'s' if load.case_count != 1 else ''}")
        if load.patient_count:
            parts.append(f"{load.patient_count} clinic patient{'s' if load.patient_count != 1 else ''}")
        work = " and ".join(parts)
        conflicts.append(OffConflict(
            surgeon_id=surgeon_id,
            surgeon_initials=surgeon.initials if surgeon else "?",
            surgeon_name=surgeon.full_name if surgeon else f"#{surgeon_id}",
            day=day,
            day_off_status=status,
            day_off_id=off_info["day_off_id"],
            case_count=load.case_count,
            patient_count=load.patient_count,
            message=f"{surgeon.initials if surgeon else '?'}: {status_label} on {day.strftime('%b %-d')} but has {work}",
        ))
    return conflicts


def should_show_as_off(
    surgeon_id: int,
    day: date,
    off_map: dict[tuple[int, date], dict],
    workloads: dict[tuple[int, date], OffWorkload],
) -> bool:
    """True when day-off/requested-off and zero patients/cases — show a synthetic OFF placeholder."""
    if (surgeon_id, day) not in off_map:
        return False
    load = workloads.get((surgeon_id, day), OffWorkload())
    return not load.has_work


def build_clinic_off_display(
    db: Session,
    start_date: date,
    end_date: date,
    *,
    sched_map: dict,
    surgical_map: dict,
    assigned_or_blocks: dict | None = None,
    or_block_overlays: dict | None = None,
) -> dict:
    """Bundle maps for Clinics/OR + calendar surfacing."""
    or_case_map: dict[int, dict[date, int]] = {}
    if assigned_or_blocks:
        for surgeon_id, by_day in assigned_or_blocks.items():
            for day, blocks in by_day.items():
                total = sum(int(block.get("caseCount") or 0) for block in blocks)
                if total:
                    or_case_map.setdefault(surgeon_id, {})[day] = total
    if or_block_overlays:
        for block in or_block_overlays.values():
            surgeon_id = block.get("surgeonId")
            day_raw = block.get("date")
            day = None
            if isinstance(day_raw, date):
                day = day_raw
            # overlays often lack date; page_data enriches separately
            if surgeon_id and day:
                cases = int(block.get("caseCount") or 0)
                if cases:
                    prev = or_case_map.setdefault(surgeon_id, {}).get(day, 0)
                    or_case_map[surgeon_id][day] = max(prev, cases)

    off_map = day_off_status_map(db, start_date, end_date)
    workloads = workload_maps(
        db, start_date, end_date,
        sched_map=sched_map,
        surgical_map=surgical_map,
        or_case_map=or_case_map or None,
    )
    conflicts = detect_off_conflicts(
        db, start_date, end_date,
        sched_map=sched_map,
        surgical_map=surgical_map,
        or_case_map=or_case_map or None,
    )

    # schedule_id -> overlay OFF on top of the fixed master schedule card.
    show_off_schedule_ids: set[int] = set()
    for surgeon_id, by_day in sched_map.items():
        for day, schedules in by_day.items():
            off_info = off_map.get((surgeon_id, day))
            if not off_info:
                continue
            if off_info.get("status") != "approved":
                continue
            for schedule in schedules:
                if (schedule.assignment_type or "assigned").lower() == "off":
                    continue
                if schedule_matches_off_session(schedule, off_info):
                    show_off_schedule_ids.add(schedule.id)

    # Legacy keys remain in the template context, but day-off display must not hide
    # the master OR/clinic card. OFF is an overlay, not a replacement.
    show_off_or_keys: set[tuple[int, date]] = set()
    hide_empty_or_blocks: dict[tuple[int, date], bool] = {}

    conflict_keys = {(c.surgeon_id, c.day) for c in conflicts}
    synthetic_off_days = {
        key for key in off_map
        if should_show_as_off(key[0], key[1], off_map, workloads)
    }

    return {
        "off_map": off_map,
        "workloads": workloads,
        "off_conflicts": conflicts,
        "off_conflict_dicts": [c.as_dict() for c in conflicts],
        "show_off_schedule_ids": show_off_schedule_ids,
        "show_off_or_keys": show_off_or_keys,
        "hide_empty_or_blocks": hide_empty_or_blocks,
        "conflict_keys": conflict_keys,
        "synthetic_off_days": synthetic_off_days,
    }
