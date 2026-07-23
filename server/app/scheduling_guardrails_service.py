"""Scheduling guardrail services for day-off review, surgical blocks, and scheduler-safe views."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from sqlalchemy import or_
from sqlalchemy.orm import Session, joinedload

from .conflicts import check_conflicts_structured
from .models import (
    ClinicGroup,
    ClinicGroupLocation,
    ClinicGroupMember,
    DayOff,
    Location,
    Meeting,
    MeetingAttendee,
    ORBlockAssignment,
    ORBlockInstance,
    Surgeon,
    SurgicalBlock,
    SurgicalCase,
)
from .surgeon_visibility import surgeon_is_visible


@dataclass(frozen=True)
class DayOffFinding:
    severity: str
    kind: str
    date: date
    message: str
    surgeon_message: str
    clinic_group_id: int | None = None
    clinic_group_name: str | None = None
    approved_initials: list[str] | None = None

    def as_dict(self) -> dict:
        return {
            "severity": self.severity,
            "kind": self.kind,
            "date": self.date.isoformat(),
            "message": self.message,
            "surgeonMessage": self.surgeon_message,
            "clinicGroupId": self.clinic_group_id,
            "clinicGroupName": self.clinic_group_name,
            "approvedInitials": self.approved_initials or [],
        }


def finding_dicts(findings: list[DayOffFinding]) -> list[dict]:
    return [finding.as_dict() for finding in findings]


def encode_findings(findings: list[DayOffFinding] | list[dict]) -> str | None:
    payload = [f.as_dict() if hasattr(f, "as_dict") else f for f in findings]
    return json.dumps(payload) if payload else None


def decode_findings(raw: str | None) -> list[dict]:
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return []
    return parsed if isinstance(parsed, list) else []


def surgeon_clinic_groups(db: Session, surgeon_id: int) -> list[ClinicGroup]:
    return (
        db.query(ClinicGroup)
        .join(ClinicGroupMember, ClinicGroupMember.clinic_group_id == ClinicGroup.id)
        .filter(
            ClinicGroupMember.surgeon_id == surgeon_id,
            ClinicGroup.is_active == True,  # noqa: E712
            ClinicGroup.group_type == "people",
        )
        .order_by(ClinicGroup.name)
        .all()
    )


def clinic_group_day_off_findings(
    db: Session,
    surgeon: Surgeon,
    start_date: date,
    end_date: date,
    exclude_dayoff_id: int | None = None,
) -> list[DayOffFinding]:
    if not surgeon:
        return []

    findings: list[DayOffFinding] = []
    groups = [
        group
        for group in surgeon_clinic_groups(db, surgeon.id)
        if group.enforce_day_off_limit
    ]
    current = start_date
    while current <= end_date:
        for group in groups:
            approved = (
                db.query(DayOff)
                .join(Surgeon, DayOff.surgeon_id == Surgeon.id)
                .join(ClinicGroupMember, ClinicGroupMember.surgeon_id == Surgeon.id)
                .filter(
                    ClinicGroupMember.clinic_group_id == group.id,
                    Surgeon.is_active == True,  # noqa: E712
                    DayOff.status.in_(("approved", "pending")),
                    DayOff.start_date <= current,
                    DayOff.end_date >= current,
                )
            )
            if exclude_dayoff_id is not None:
                approved = approved.filter(DayOff.id != exclude_dayoff_id)
            approved_rows = [
                row
                for row in approved.options(joinedload(DayOff.surgeon)).all()
                if surgeon_is_visible(row.surgeon)
            ]
            limit = max(1, int(group.max_approved_off_per_day or 1))
            if len(approved_rows) < limit:
                continue
            initials = sorted({row.surgeon.initials for row in approved_rows if row.surgeon})
            initials_text = ", ".join(initials)
            day_label = current.strftime("%b %-d")
            pending_n = sum(1 for row in approved_rows if row.status == "pending")
            approved_n = len(approved_rows) - pending_n
            detail = f"{approved_n} approved"
            if pending_n:
                detail += f", {pending_n} pending"
            findings.append(DayOffFinding(
                severity="warning",
                kind="clinic_group_capacity",
                date=current,
                clinic_group_id=group.id,
                clinic_group_name=group.name,
                approved_initials=initials,
                surgeon_message=(
                    f"{group.name} already has {initials_text} off/pending on {day_label}. Shannon will review."
                ),
                message=(
                    f"Clinic group capacity: {group.name} allows {limit} member"
                    f"{'' if limit == 1 else 's'} off per day (approved + pending). "
                    f"{day_label} already has {detail}: {initials_text}."
                ),
            ))
        current += timedelta(days=1)
    return findings


def dayoff_review_findings(db: Session, dayoff: DayOff) -> list[DayOffFinding]:
    from .scheduling_gate_service import build_dayoff_review_findings
    return build_dayoff_review_findings(db, dayoff)


def store_dayoff_findings(db: Session, dayoff: DayOff) -> list[DayOffFinding]:
    from .scheduling_gate_service import store_full_dayoff_findings
    return store_full_dayoff_findings(db, dayoff)


def dayoff_surgeon_warning(findings: list[DayOffFinding] | list[dict]) -> str:
    from .scheduling_gate_service import surgeon_friendly_conflict_message
    return surgeon_friendly_conflict_message(findings)


def memberships_by_group(db: Session) -> dict[int, set[int]]:
    out: dict[int, set[int]] = {}
    for row in db.query(ClinicGroupMember).all():
        out.setdefault(row.clinic_group_id, set()).add(row.surgeon_id)
    return out


def locations_by_group(db: Session) -> dict[int, set[int]]:
    out: dict[int, set[int]] = {}
    for row in db.query(ClinicGroupLocation).all():
        out.setdefault(row.clinic_group_id, set()).add(row.location_id)
    return out


def replace_clinic_group_members(db: Session, group_id: int, surgeon_ids: list[int]) -> None:
    db.query(ClinicGroupMember).filter(ClinicGroupMember.clinic_group_id == group_id).delete()
    seen = set()
    for surgeon_id in surgeon_ids:
        if surgeon_id in seen:
            continue
        seen.add(surgeon_id)
        db.add(ClinicGroupMember(clinic_group_id=group_id, surgeon_id=surgeon_id))
    db.commit()


def replace_clinic_group_locations(db: Session, group_id: int, location_ids: list[int]) -> None:
    db.query(ClinicGroupLocation).filter(ClinicGroupLocation.clinic_group_id == group_id).delete()
    seen = set()
    for location_id in location_ids:
        if location_id in seen:
            continue
        seen.add(location_id)
        db.add(ClinicGroupLocation(clinic_group_id=group_id, location_id=location_id))
    db.commit()


def day_block_range(block: SurgicalBlock, case_date: date) -> tuple[datetime, datetime]:
    return datetime.combine(case_date, block.start_time), datetime.combine(case_date, block.end_time)


def case_range(case_date: date, start_time: time, end_time: time | None) -> tuple[datetime, datetime]:
    start = datetime.combine(case_date, start_time)
    end = datetime.combine(case_date, end_time) if end_time else start + timedelta(hours=1)
    return start, end


def active_blocks_for_case(db: Session, surgeon_id: int, case_date: date) -> list[SurgicalBlock]:
    return (
        db.query(SurgicalBlock)
        .filter(
            SurgicalBlock.surgeon_id == surgeon_id,
            SurgicalBlock.is_active == True,  # noqa: E712
            or_(
                SurgicalBlock.block_date == case_date,
                (SurgicalBlock.block_date.is_(None) & (SurgicalBlock.day_of_week == case_date.weekday())),
            ),
        )
        .order_by(SurgicalBlock.start_time)
        .all()
    )


def active_or_block_instances_for_case(
    db: Session,
    surgeon_id: int,
    case_date: date,
    *,
    or_block_instance_id: int | None = None,
) -> list[ORBlockInstance]:
    """Block OR inventory (preferred) for surgeon/day — supersedes legacy SurgicalBlock."""
    if or_block_instance_id:
        linked = db.get(ORBlockInstance, or_block_instance_id)
        if linked and linked.date == case_date and (linked.status or "") != "released":
            return [linked]
    rows = (
        db.query(ORBlockInstance)
        .options(joinedload(ORBlockInstance.location))
        .join(ORBlockAssignment, ORBlockAssignment.block_instance_id == ORBlockInstance.id)
        .filter(
            ORBlockAssignment.surgeon_id == surgeon_id,
            ORBlockInstance.date == case_date,
            ORBlockInstance.status.in_(["open", "assigned"]),
        )
        .order_by(ORBlockInstance.start_time, ORBlockInstance.id)
        .all()
    )
    return rows


def surgical_case_warning_messages(
    db: Session,
    surgeon_id: int,
    case_date: date,
    start_time: time,
    end_time: time | None,
    location_id: int | None = None,
    exclude_case_id: int | None = None,
    or_block_instance_id: int | None = None,
) -> list[str]:
    warnings: list[str] = []
    case_start, case_end = case_range(case_date, start_time, end_time)

    or_instances = active_or_block_instances_for_case(
        db, surgeon_id, case_date, or_block_instance_id=or_block_instance_id
    )
    legacy_blocks = active_blocks_for_case(db, surgeon_id, case_date) if not or_instances else []

    if or_instances:
        inside_any = False
        for block in or_instances:
            block_start = datetime.combine(case_date, block.start_time)
            block_end = datetime.combine(case_date, block.end_time)
            same_location = not location_id or not block.location_id or block.location_id == location_id
            if same_location and block_start <= case_start and case_end <= block_end:
                inside_any = True
                break
        if not inside_any:
            block_labels = ", ".join(
                f"{b.start_time.strftime('%H:%M')}-{b.end_time.strftime('%H:%M')}"
                + (f" {b.location.abbreviation}" if b.location and b.location.abbreviation else "")
                for b in or_instances
            )
            warnings.append(f"Outside surgical block time. Available block(s): {block_labels}.")
    elif legacy_blocks:
        inside_any = False
        for block in legacy_blocks:
            block_start, block_end = day_block_range(block, case_date)
            same_location = not location_id or not block.location_id or block.location_id == location_id
            if same_location and block_start <= case_start and case_end <= block_end:
                inside_any = True
                break
        if not inside_any:
            block_labels = ", ".join(
                f"{b.start_time.strftime('%H:%M')}-{b.end_time.strftime('%H:%M')}"
                + (f" {b.location.abbreviation}" if b.location else "")
                for b in legacy_blocks
            )
            warnings.append(f"Outside surgical block time. Available block(s): {block_labels}.")
    else:
        warnings.append("No surgical block is defined for this surgeon on this day.")

    conflicts = check_conflicts_structured(
        surgeon_id,
        case_date,
        case_date,
        db,
        exclude_entity=("surgical_case", exclude_case_id) if exclude_case_id else None,
        target_entity={
            "type": "surgical_case",
            "date": case_date,
            "start_time": start_time,
            "end_time": end_time,
            "location_id": location_id,
            "or_block_instance_id": or_block_instance_id,
        },
    )
    for conflict in conflicts:
        # Cases belong inside Block OR — overlapping own/same-facility capacity is not a warning.
        if conflict.rule_id == "OVERLAP_OR_BLOCK":
            continue
        if conflict.rule_id.startswith("BUFFER_") or conflict.rule_id.startswith("LOCATION_"):
            warnings.append(conflict.message)
            continue
        label = {
            "OVERLAP_SURGERY": "Overlaps another surgical case",
            "OVERLAP_CLINIC": "Overlaps clinic schedule",
            "OVERLAP_DAY_OFF": "Overlaps approved day off",
            "OVERLAP_MEETING": "Overlaps assigned meeting",
            "OVERLAP_UNAVAILABLE": "Overlaps unavailable time",
            "OVERLAP_CALL": "Surgeon is on call",
        }.get(conflict.rule_id, "Schedule warning")
        warnings.append(f"{label}: {conflict.message}")

    deduped = []
    for msg in warnings:
        if msg and msg not in deduped:
            deduped.append(msg)
    return deduped


def scheduler_safe_warning(message: str) -> str:
    """Keep Advent/scheduler-facing warnings useful without exposing patient details."""
    if "Surgery on " in message and " — " in message:
        return message.split(" — ", 1)[0].rstrip() + " — existing case)"
    return message


def scheduler_safe_rows(db: Session, start_date: date, end_date: date, surgeon_id: int | None = None) -> list[dict]:
    q = (
        db.query(SurgicalCase)
        .join(Surgeon, SurgicalCase.surgeon_id == Surgeon.id)
        .filter(
            SurgicalCase.date >= start_date,
            SurgicalCase.date <= end_date,
            SurgicalCase.status != "cancelled",
            Surgeon.is_active == True,  # noqa: E712
        )
        .options(joinedload(SurgicalCase.surgeon), joinedload(SurgicalCase.location))
        .order_by(SurgicalCase.date, SurgicalCase.start_time)
    )
    if surgeon_id:
        q = q.filter(SurgicalCase.surgeon_id == surgeon_id)
    rows = []
    for case in q.all():
        if not surgeon_is_visible(case.surgeon):
            continue
        warnings = surgical_case_warning_messages(
            db,
            case.surgeon_id,
            case.date,
            case.start_time,
            case.end_time,
            case.location_id,
            exclude_case_id=case.id,
            or_block_instance_id=case.or_block_instance_id,
        )
        rows.append({
            "date": case.date,
            "start": case.start_time,
            "end": case.end_time,
            "surgeon": case.surgeon.full_name if case.surgeon else "",
            "surgeon_initials": case.surgeon.initials if case.surgeon else "",
            "location": case.location.name if case.location else (case.room_text or "OR"),
            "procedure": case.procedure or "",
            "status": case.status or "scheduled",
            "warnings": [scheduler_safe_warning(warning) for warning in warnings],
        })
    return rows


def scheduler_meetings_for_surgeon(db: Session, surgeon_id: int, start_date: date, end_date: date) -> list[Meeting]:
    return (
        db.query(Meeting)
        .outerjoin(MeetingAttendee)
        .filter(
            Meeting.date >= start_date,
            Meeting.date <= end_date,
            or_(MeetingAttendee.surgeon_id == surgeon_id, ~Meeting.attendees.any()),
        )
        .distinct()
        .all()
    )
