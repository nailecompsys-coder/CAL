"""Day-off vs clinic/OR workload: display OFF and flag Shannon conflicts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy.orm import Session, joinedload

from .admin_clinic_schedule_page_service import parse_clinic_fax_visit_segments
from .models import ClinicSchedule, DayOff, Surgeon, SurgicalCase
from .surgeon_visibility import surgeon_is_visible


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
        db.query(DayOff)
        .options(joinedload(DayOff.surgeon))
        .filter(
            DayOff.start_date <= end_date,
            DayOff.end_date >= start_date,
            DayOff.status.in_(("approved", "pending")),
        )
        .all()
    )
    out: dict[tuple[int, date], dict] = {}
    for row in rows:
        if not surgeon_is_visible(row.surgeon):
            continue
        current = max(row.start_date, start_date)
        last = min(row.end_date, end_date)
        while current <= last:
            key = (row.surgeon_id, current)
            existing = out.get(key)
            # Prefer approved; keep earliest pending if no approved.
            if existing and existing["status"] == "approved":
                current += timedelta(days=1)
                continue
            if row.status == "approved" or not existing:
                out[key] = {
                    "status": row.status,
                    "day_off_id": row.id,
                    "reason": row.reason,
                    "surgeon": row.surgeon,
                }
            current += timedelta(days=1)
    return out


def clinic_patient_count_for_schedules(schedules: list[ClinicSchedule]) -> int:
    total = 0
    for schedule in schedules:
        if (schedule.assignment_type or "assigned").lower() == "off":
            continue
        total += len(parse_clinic_fax_visit_segments(schedule.notes or ""))
    return total


def aprima_patient_counts(
    db: Session,
    start_date: date,
    end_date: date,
    surgeons_by_id: dict[int, Surgeon],
) -> dict[tuple[int, date], int]:
    """Count non-surgery Aprima appointments per surgeon/day (cache-first, never raises)."""
    counts: dict[tuple[int, date], int] = {}
    try:
        from .aprima_cache_service import patient_appointments_for_api
        from .aprima_schedule_service import appointment_belongs_to_surgeon, is_surgery_appointment
    except Exception:  # noqa: BLE001
        return counts
    try:
        payload = patient_appointments_for_api(db, start_date, end_date, surgeon=None)
    except Exception:  # noqa: BLE001
        return counts
    rows = payload.get("appointments") or []
    if not rows or not surgeons_by_id:
        return counts
    for row in rows:
        if is_surgery_appointment(row):
            continue
        day_raw = (row.get("date") or "")[:10]
        if not day_raw:
            continue
        try:
            day = date.fromisoformat(day_raw)
        except ValueError:
            continue
        if day < start_date or day > end_date:
            continue
        for surgeon in surgeons_by_id.values():
            if appointment_belongs_to_surgeon(row, surgeon):
                key = (surgeon.id, day)
                counts[key] = counts.get(key, 0) + 1
                break
    return counts


def workload_maps(
    db: Session,
    start_date: date,
    end_date: date,
    *,
    sched_map: dict | None = None,
    surgical_map: dict | None = None,
    or_case_map: dict | None = None,
) -> dict[tuple[int, date], OffWorkload]:
    """Aggregate cases + clinic patients for surgeon/day keys."""
    if sched_map is None:
        schedules = (
            db.query(ClinicSchedule)
            .filter(ClinicSchedule.date >= start_date, ClinicSchedule.date <= end_date)
            .all()
        )
        sched_map = {}
        for schedule in schedules:
            sched_map.setdefault(schedule.surgeon_id, {}).setdefault(schedule.date, []).append(schedule)

    if surgical_map is None:
        cases = (
            db.query(SurgicalCase)
            .filter(
                SurgicalCase.date >= start_date,
                SurgicalCase.date <= end_date,
                SurgicalCase.status != "cancelled",
            )
            .all()
        )
        surgical_map = {}
        for case in cases:
            surgical_map.setdefault(case.surgeon_id, {}).setdefault(case.date, []).append(case)

    surgeon_ids = set(sched_map.keys()) | set(surgical_map.keys())
    if or_case_map:
        surgeon_ids |= set(or_case_map.keys())
    surgeons_by_id = {}
    for sid in surgeon_ids:
        surgeon = db.get(Surgeon, sid)
        if surgeon and surgeon_is_visible(surgeon):
            surgeons_by_id[sid] = surgeon
    aprima_counts = aprima_patient_counts(db, start_date, end_date, surgeons_by_id)

    out: dict[tuple[int, date], OffWorkload] = {}
    all_days = []
    current = start_date
    while current <= end_date:
        all_days.append(current)
        current += timedelta(days=1)

    for surgeon_id in surgeon_ids | {k[0] for k in aprima_counts}:
        for day in all_days:
            schedules = (sched_map.get(surgeon_id) or {}).get(day, []) or []
            cases = (surgical_map.get(surgeon_id) or {}).get(day, []) or []
            or_cases = 0
            if or_case_map:
                or_cases = int((or_case_map.get(surgeon_id) or {}).get(day, 0) or 0)
            patients = clinic_patient_count_for_schedules(schedules) + aprima_counts.get((surgeon_id, day), 0)
            case_count = len(cases) + or_cases
            # SurgicalCase rows already cover live OR cases; avoid double-count when
            # or_case_map is derived from the same cases. Prefer max of live cases vs OR pill.
            if cases and or_cases:
                case_count = max(len(cases), or_cases)
            elif cases:
                case_count = len(cases)
            else:
                case_count = or_cases
            if case_count or patients or schedules:
                out[(surgeon_id, day)] = OffWorkload(case_count=case_count, patient_count=patients)
    return out


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
    """True when day-off/requested-off and zero patients/cases — show OFF instead of empty clinic/OR."""
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

    # schedule_id -> show as OFF (empty slot on off day)
    show_off_schedule_ids: set[int] = set()
    for surgeon_id, by_day in sched_map.items():
        for day, schedules in by_day.items():
            if not should_show_as_off(surgeon_id, day, off_map, workloads):
                continue
            for schedule in schedules:
                if (schedule.assignment_type or "assigned").lower() == "off":
                    continue
                # Empty clinic/OR location pill → display as OFF
                show_off_schedule_ids.add(schedule.id)

    # OR block pills with zero cases on off days → hide / show OFF
    show_off_or_keys: set[tuple[int, date]] = set()
    hide_empty_or_blocks: dict[tuple[int, date], bool] = {}
    for surgeon_id, by_day in (assigned_or_blocks or {}).items():
        for day, blocks in by_day.items():
            if (surgeon_id, day) not in off_map:
                continue
            load = workloads.get((surgeon_id, day), OffWorkload())
            if load.has_work:
                continue
            total_cases = sum(int(b.get("caseCount") or 0) for b in blocks)
            if total_cases == 0:
                show_off_or_keys.add((surgeon_id, day))
                hide_empty_or_blocks[(surgeon_id, day)] = True

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
