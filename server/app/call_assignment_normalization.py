"""Read the live call list.

One call row is one date and one group on call_rotations. The hospitals in
that group come from call_group_locations. The old per-hospital copy is not
the schedule answer, so these helpers no longer write it.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from sqlalchemy.orm import Session, selectinload

from .models import CallCoverage, CallGroup, CallGroupLocation, CallRotation, Location, Surgeon


@dataclass
class EffectiveCall:
    """One live call cell: the covering surgeon when a cover is active."""

    rotation: CallRotation
    coverage: CallCoverage | None
    surgeon_id: int
    surgeon: Surgeon | None
    locations: list[Location]

    @property
    def date(self) -> date:
        return self.rotation.date

    @property
    def call_rotation_id(self) -> int:
        return self.rotation.id

    @property
    def call_group_id(self) -> int | None:
        return self.rotation.call_group_id

    @property
    def call_group(self) -> CallGroup | None:
        return self.rotation.call_group

    @property
    def call_coverage_id(self) -> int | None:
        return self.coverage.id if self.coverage else None

    @property
    def original_surgeon_id(self) -> int | None:
        return self.rotation.surgeon_id

    @property
    def original_surgeon(self) -> Surgeon | None:
        return self.rotation.surgeon

    @property
    def place(self) -> str:
        """Hospital abbreviations for this group, or the group name."""
        labels = []
        for location in self.locations:
            label = (location.abbreviation or location.name or "").strip()
            if label and label not in labels:
                labels.append(label)
        if labels:
            return ", ".join(labels)
        if self.call_group and self.call_group.name:
            return self.call_group.name
        return "call"


def _active_coverage(rotation: CallRotation) -> CallCoverage | None:
    active = [coverage for coverage in (rotation.coverages or []) if coverage.status == "active"]
    if not active:
        return None
    return max(active, key=lambda coverage: coverage.id or 0)


def effective_calls(
    db: Session,
    start: date,
    end: date,
    surgeon_id: int | None = None,
) -> list[EffectiveCall]:
    """Live call cells in the date window. One cell per date and group."""
    rotations = (
        db.query(CallRotation)
        .options(
            selectinload(CallRotation.surgeon),
            selectinload(CallRotation.call_group)
            .selectinload(CallGroup.locations)
            .selectinload(CallGroupLocation.location),
            selectinload(CallRotation.coverages).selectinload(CallCoverage.covering_surgeon),
        )
        .filter(
            CallRotation.date >= start,
            CallRotation.date <= end,
            CallRotation.call_group_id.isnot(None),
        )
        .order_by(CallRotation.date, CallRotation.call_group_id, CallRotation.id)
        .all()
    )
    rows: list[EffectiveCall] = []
    seen: set[int] = set()
    for rotation in rotations:
        if rotation.id in seen:
            continue
        seen.add(rotation.id)
        coverage = _active_coverage(rotation)
        effective_id = coverage.covering_surgeon_id if coverage else rotation.surgeon_id
        if effective_id is None:
            continue
        if surgeon_id is not None and effective_id != surgeon_id:
            continue
        surgeon = coverage.covering_surgeon if coverage else rotation.surgeon
        locations = []
        if rotation.call_group:
            links = sorted(rotation.call_group.locations or [], key=lambda link: link.location_id or 0)
            for link in links:
                if link.location is not None:
                    locations.append(link.location)
        rows.append(EffectiveCall(
            rotation=rotation,
            coverage=coverage,
            surgeon_id=effective_id,
            surgeon=surgeon,
            locations=locations,
        ))
    return rows


def sync_call_rotation(db: Session, rotation: CallRotation) -> int:
    """Kept so callers still compile. The live row is already call_rotations."""
    del db, rotation
    return 0


def backfill_call_daily_assignments(db: Session) -> int:
    """Kept so startup still compiles. Screens no longer read the hospital copy."""
    del db
    return 0
