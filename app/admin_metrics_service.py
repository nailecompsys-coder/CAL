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
    requested_days: float = 0.0
    approved_days: float = 0.0
    scheduled_call_days: int = 0
    taken_call_days: int = 0
    scheduled_by_group: dict[int, int] = field(default_factory=lambda: defaultdict(int))
    taken_by_group: dict[int, int] = field(default_factory=lambda: defaultdict(int))

    @property
    def call_delta(self) -> int:
        return self.taken_call_days - self.scheduled_call_days


def build_admin_metrics(db: Session, start_date: date, end_date: date, staff_type: str = "physician") -> dict:
    cohort = "physician" if staff_type == "physician" else "staff"
    surgeons = _active_people_for_cohort(db, cohort)
    metrics_by_id = {surgeon.id: PersonMetrics(surgeon=surgeon) for surgeon in surgeons}

    _apply_day_off_metrics(db, metrics_by_id, start_date, end_date)
    groups = _call_groups(db)
    group_meta = {
        group.id: {
            "id": group.id,
            "name": group.name,
            "scheduled_total": 0,
            "taken_total": 0,
            "rows": [],
        }
        for group in groups
    }
    _apply_call_metrics(db, metrics_by_id, group_meta, start_date, end_date, cohort)

    rows = sorted(metrics_by_id.values(), key=lambda item: _surgeon_sort_key(item.surgeon))
    totals = {
        "requested_days": sum(item.requested_days for item in rows),
        "approved_days": sum(item.approved_days for item in rows),
        "scheduled_call_days": sum(item.scheduled_call_days for item in rows),
        "taken_call_days": sum(item.taken_call_days for item in rows),
    }
    totals["call_delta"] = totals["taken_call_days"] - totals["scheduled_call_days"]

    group_rows = []
    for group in groups:
        meta = group_meta[group.id]
        people = []
        for item in rows:
            scheduled = item.scheduled_by_group.get(group.id, 0)
            taken = item.taken_by_group.get(group.id, 0)
            scheduled_total = meta["scheduled_total"] or 0
            taken_total = meta["taken_total"] or 0
            people.append({
                "surgeon": item.surgeon,
                "scheduled": scheduled,
                "taken": taken,
                "delta": taken - scheduled,
                "scheduled_percent": _percent(scheduled, scheduled_total),
                "taken_percent": _percent(taken, taken_total),
            })
        group_rows.append({
            "id": group.id,
            "name": group.name,
            "scheduled_total": meta["scheduled_total"],
            "taken_total": meta["taken_total"],
            "people": people,
        })

    return {
        "staff_type": cohort,
        "staff_label": "Surgeons" if cohort == "physician" else "PAs / Staff",
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
    return [
        surgeon
        for surgeon in rows
        if _cohort_for_surgeon(surgeon) == staff_type
    ]


def _apply_day_off_metrics(
    db: Session,
    metrics_by_id: dict[int, PersonMetrics],
    start_date: date,
    end_date: date,
) -> None:
    rows = (
        db.query(DayOff)
        .filter(
            DayOff.status.in_(["pending", "approved"]),
            DayOff.start_date <= end_date,
            DayOff.end_date >= start_date,
        )
        .all()
    )
    for row in rows:
        metrics = metrics_by_id.get(row.surgeon_id)
        if not metrics:
            continue
        weight = _clipped_day_off_weight(row, start_date, end_date)
        metrics.requested_days += weight
        if row.status == "approved":
            metrics.approved_days += weight


def _apply_call_metrics(
    db: Session,
    metrics_by_id: dict[int, PersonMetrics],
    group_meta: dict[int, dict],
    start_date: date,
    end_date: date,
    staff_type: str,
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
        if original and _cohort_for_surgeon(original) == staff_type:
            metrics = metrics_by_id.get(original.id)
            if metrics:
                metrics.scheduled_call_days += 1
                metrics.scheduled_by_group[group_id] += 1
                group_meta[group_id]["scheduled_total"] += 1

        coverage = active_coverage_for_rotation(rotation)
        effective = coverage.covering_surgeon if coverage and coverage.covering_surgeon else original
        if effective and _cohort_for_surgeon(effective) == staff_type:
            metrics = metrics_by_id.get(effective.id)
            if metrics:
                metrics.taken_call_days += 1
                metrics.taken_by_group[group_id] += 1
                group_meta[group_id]["taken_total"] += 1


def _call_groups(db: Session) -> list[CallGroup]:
    return db.query(CallGroup).order_by(CallGroup.sort_order, CallGroup.name, CallGroup.id).all()


def _clipped_day_off_weight(row: DayOff, start_date: date, end_date: date) -> float:
    total = 0.0
    for segment in day_off_segments(row):
        segment_date_raw = segment.get("date")
        if not segment_date_raw:
            continue
        try:
            segment_date = date.fromisoformat(str(segment_date_raw))
        except ValueError:
            continue
        if start_date <= segment_date <= end_date:
            total += day_off_weight(segment)
    return total


def _cohort_for_surgeon(surgeon: Surgeon) -> str:
    return "physician" if (surgeon.staff_type or "physician") == "physician" else "staff"


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
