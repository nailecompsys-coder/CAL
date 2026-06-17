"""Admin operations metrics for schedule balance reporting."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date

from sqlalchemy.orm import Session, joinedload

from .models import CallCoverage, CallGroup, CallRotation, DayOff, Surgeon
from .native_call_support import active_coverage_for_rotation
from .native_dayoff_support import day_off_segments


@dataclass
class PersonMetrics:
    surgeon: Surgeon
    day_off_taken: float = 0.0
    day_off_approved_upcoming: float = 0.0
    call_taken: int = 0
    call_scheduled_upcoming: int = 0
    call_taken_by_group: dict[int, int] = field(default_factory=lambda: defaultdict(int))
    call_scheduled_by_group: dict[int, int] = field(default_factory=lambda: defaultdict(int))

    @property
    def role_label(self) -> str:
        return "Surgeon" if _cohort_for_surgeon(self.surgeon) == "physician" else "PA / Staff"


def build_admin_metrics(db: Session, start_date: date, end_date: date, staff_type: str = "all", today: date | None = None) -> dict:
    as_of = today or date.today()
    cohort = _normalized_staff_type(staff_type)
    surgeons = _active_people_for_cohort(db, cohort)
    metrics_by_id = {surgeon.id: PersonMetrics(surgeon=surgeon) for surgeon in surgeons}

    _apply_day_off_metrics(db, metrics_by_id, start_date, end_date, as_of)
    groups = _call_groups(db)
    group_meta = {
        group.id: {
            "id": group.id,
            "name": group.name,
            "scheduled_total_by_cohort": defaultdict(int),
            "taken_total_by_cohort": defaultdict(int),
        }
        for group in groups
    }
    _apply_call_metrics(db, metrics_by_id, group_meta, start_date, end_date, cohort, as_of)

    rows = sorted(metrics_by_id.values(), key=lambda item: _surgeon_sort_key(item.surgeon))
    totals = {
        "day_off_taken": sum(item.day_off_taken for item in rows),
        "day_off_approved_upcoming": sum(item.day_off_approved_upcoming for item in rows),
        "call_taken": sum(item.call_taken for item in rows),
        "call_scheduled_upcoming": sum(item.call_scheduled_upcoming for item in rows),
    }

    group_rows = []
    for group in groups:
        meta = group_meta[group.id]
        people = []
        for item in rows:
            person_cohort = _cohort_for_surgeon(item.surgeon)
            scheduled = item.call_scheduled_by_group.get(group.id, 0)
            taken = item.call_taken_by_group.get(group.id, 0)
            scheduled_total = meta["scheduled_total_by_cohort"].get(person_cohort, 0)
            taken_total = meta["taken_total_by_cohort"].get(person_cohort, 0)
            people.append({
                "surgeon": item.surgeon,
                "role": item.role_label,
                "scheduled": scheduled,
                "taken": taken,
                "scheduled_percent": _percent(scheduled, scheduled_total),
                "taken_percent": _percent(taken, taken_total),
            })
        group_rows.append({
            "id": group.id,
            "name": group.name,
            "scheduled_total": sum(meta["scheduled_total_by_cohort"].values()),
            "taken_total": sum(meta["taken_total_by_cohort"].values()),
            "people": people,
        })

    return {
        "staff_type": cohort,
        "staff_label": _staff_label(cohort),
        "as_of": as_of,
        "start_date": start_date,
        "end_date": end_date,
        "totals": totals,
        "rows": rows,
        "groups": group_rows,
    }


def default_metrics_range(today: date) -> tuple[date, date]:
    return date(today.year, 1, 1), date(today.year, 12, 31)


def day_off_weight(segment: dict) -> float:
    if segment.get("isFullDay", True):
        return 1.0
    return 0.5


def _active_people_for_cohort(db: Session, staff_type: str) -> list[Surgeon]:
    rows = (
        db.query(Surgeon)
        .filter(Surgeon.is_active == True)  # noqa: E712
        .order_by(Surgeon.sort_order, Surgeon.last_name, Surgeon.first_name)
        .all()
    )
    if staff_type == "all":
        return rows
    return [surgeon for surgeon in rows if _cohort_for_surgeon(surgeon) == staff_type]


def _apply_day_off_metrics(
    db: Session,
    metrics_by_id: dict[int, PersonMetrics],
    start_date: date,
    end_date: date,
    today: date,
) -> None:
    rows = (
        db.query(DayOff)
        .filter(
            DayOff.status == "approved",
            DayOff.start_date <= end_date,
            DayOff.end_date >= start_date,
        )
        .all()
    )
    for row in rows:
        metrics = metrics_by_id.get(row.surgeon_id)
        if not metrics:
            continue
        taken, upcoming = _split_day_off_weight(row, start_date, end_date, today)
        metrics.day_off_taken += taken
        metrics.day_off_approved_upcoming += upcoming


def _apply_call_metrics(
    db: Session,
    metrics_by_id: dict[int, PersonMetrics],
    group_meta: dict[int, dict],
    start_date: date,
    end_date: date,
    staff_type: str,
    today: date,
) -> None:
    rotations = (
        db.query(CallRotation)
        .options(
            joinedload(CallRotation.surgeon),
            joinedload(CallRotation.call_group),
            joinedload(CallRotation.coverages).joinedload(CallCoverage.covering_surgeon),
        )
        .filter(
            CallRotation.date >= start_date,
            CallRotation.date <= end_date,
            CallRotation.surgeon_id.isnot(None),
            CallRotation.call_group_id.isnot(None),
        )
        .order_by(CallRotation.date, CallRotation.call_group_id, CallRotation.id)
        .all()
    )

    for rotation in rotations:
        group_id = rotation.call_group_id
        if group_id not in group_meta:
            group_meta[group_id] = {
                "id": group_id,
                "name": rotation.call_group.name if rotation.call_group else "Call",
                "scheduled_total": 0,
                "taken_total": 0,
                "rows": [],
            }

        original = rotation.surgeon
        coverage = active_coverage_for_rotation(rotation)
        effective = coverage.covering_surgeon if coverage and coverage.covering_surgeon else original
        if not effective:
            continue
        effective_cohort = _cohort_for_surgeon(effective)
        if staff_type != "all" and effective_cohort != staff_type:
            continue
        metrics = metrics_by_id.get(effective.id)
        if not metrics:
            continue
        if rotation.date <= today:
            metrics.call_taken += 1
            metrics.call_taken_by_group[group_id] += 1
            group_meta[group_id]["taken_total_by_cohort"][effective_cohort] += 1
        else:
            metrics.call_scheduled_upcoming += 1
            metrics.call_scheduled_by_group[group_id] += 1
            group_meta[group_id]["scheduled_total_by_cohort"][effective_cohort] += 1


def _call_groups(db: Session) -> list[CallGroup]:
    return db.query(CallGroup).order_by(CallGroup.sort_order, CallGroup.name, CallGroup.id).all()


def _split_day_off_weight(row: DayOff, start_date: date, end_date: date, today: date) -> tuple[float, float]:
    taken = 0.0
    upcoming = 0.0
    for segment in day_off_segments(row):
        segment_date_raw = segment.get("date")
        if not segment_date_raw:
            continue
        try:
            segment_date = date.fromisoformat(str(segment_date_raw))
        except ValueError:
            continue
        if not start_date <= segment_date <= end_date:
            continue
        if segment_date <= today:
            taken += day_off_weight(segment)
        else:
            upcoming += day_off_weight(segment)
    return taken, upcoming


def _cohort_for_surgeon(surgeon: Surgeon) -> str:
    return "physician" if (surgeon.staff_type or "physician") == "physician" else "staff"


def _normalized_staff_type(staff_type: str) -> str:
    if staff_type == "physician":
        return "physician"
    if staff_type == "staff":
        return "staff"
    return "all"


def _staff_label(staff_type: str) -> str:
    if staff_type == "physician":
        return "Surgeons"
    if staff_type == "staff":
        return "PAs / Staff"
    return "Surgeons and PAs / Staff"


def _surgeon_sort_key(surgeon: Surgeon) -> tuple:
    rank = surgeon.sort_order or 0
    return (
        rank if rank > 0 else 999999,
        (surgeon.last_name or "").lower(),
        (surgeon.first_name or "").lower(),
        surgeon.id or 0,
    )


def _percent(value: int, total: int) -> float:
    if not total:
        return 0.0
    return round((value / total) * 100, 1)
