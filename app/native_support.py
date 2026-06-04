"""Shared helpers for the native iOS API surface."""
import json
from collections import defaultdict
from datetime import date, time, timedelta

from fastapi import HTTPException
from sqlalchemy import or_
from sqlalchemy.orm import Session, joinedload

from .models import CallCoverage, CallRotation, DayOff, Meeting, MeetingAttendee, NativeScheduleAlert, Surgeon


def parse_hhmm(raw: str | None) -> time | None:
    if not raw:
        return None
    try:
        hour, minute = raw.split(":")[:2]
        return time(int(hour), int(minute))
    except Exception:
        return None


def fmt_time(value: time | None) -> str | None:
    return value.strftime("%H:%M") if value else None


def session_times(session: str | None) -> tuple[str, str]:
    if session == "am":
        return ("08:00", "12:00")
    if session == "pm":
        return ("13:00", "17:00")
    return ("08:00", "17:00")


def date_label(d: date) -> dict:
    return {
        "date": d.isoformat(),
        "dayName": d.strftime("%A"),
        "dayShort": d.strftime("%a"),
        "dayFull": d.strftime("%m-%d-%Y"),
    }


def native_surgeon_rank_key(surgeon: Surgeon | None) -> tuple:
    if not surgeon:
        return (2, 999999, "", "")
    is_physician = (surgeon.staff_type or "physician") == "physician"
    rank = surgeon.sort_order or 0
    return (
        0 if is_physician else 1,
        rank if is_physician and rank > 0 else 999999,
        (surgeon.last_name or "").lower(),
        (surgeon.first_name or "").lower(),
    )


def day_off_segments(row: DayOff) -> list[dict]:
    if row.segments:
        try:
            parsed = json.loads(row.segments)
            if isinstance(parsed, list):
                return parsed
        except json.JSONDecodeError:
            pass
    segments = []
    current = row.start_date
    while current <= row.end_date:
        segments.append({
            "date": current.isoformat(),
            "isFullDay": row.is_full_day if row.is_full_day is not None else True,
            "start": fmt_time(row.start_time),
            "end": fmt_time(row.end_time),
        })
        current += timedelta(days=1)
    return segments


def segment_for_date(row: DayOff, d: date) -> dict | None:
    for segment in day_off_segments(row):
        if segment.get("date") == d.isoformat():
            return segment
    return None


def serialize_day_off(row: DayOff) -> dict:
    return {
        "id": row.id,
        "surgeonId": row.surgeon_id,
        "surgeonName": row.surgeon.full_name if row.surgeon else "",
        "surgeonInitials": row.surgeon.initials if row.surgeon else "",
        "surgeonSortOrder": row.surgeon.sort_order if row.surgeon else 0,
        "startDate": row.start_date.isoformat(),
        "endDate": row.end_date.isoformat(),
        "reason": row.reason or "",
        "notes": row.notes or "",
        "adminNote": row.admin_note or "",
        "status": row.status or "pending",
        "isFullDay": row.is_full_day if row.is_full_day is not None else True,
        "start": fmt_time(row.start_time),
        "end": fmt_time(row.end_time),
        "segments": day_off_segments(row),
    }


def normalize_day_off_segments(
    sd: date,
    ed: date,
    is_full_day: bool,
    start: str | None,
    end: str | None,
    raw: list | None,
) -> list[dict]:
    by_date = {str(item.get("date")): item for item in raw or [] if isinstance(item, dict)}
    segments = []
    current = sd
    while current <= ed:
        item = by_date.get(current.isoformat(), {})
        full = item.get("isFullDay", is_full_day)
        start_value = None if full else (item.get("start") or start)
        end_value = None if full else (item.get("end") or end)
        segments.append({
            "date": current.isoformat(),
            "isFullDay": bool(full),
            "start": start_value,
            "end": end_value,
        })
        current += timedelta(days=1)
    return segments


def validate_day_off_segments(segments: list[dict]) -> None:
    for segment in segments:
        if segment.get("isFullDay"):
            continue
        start_t = parse_hhmm(str(segment.get("start") or ""))
        end_t = parse_hhmm(str(segment.get("end") or ""))
        if not start_t or not end_t or end_t <= start_t:
            raise HTTPException(400, "Partial days need a valid start and end time.")


def serialize_native_alert(row: NativeScheduleAlert) -> dict:
    try:
        payload = json.loads(row.payload or "{}")
    except json.JSONDecodeError:
        payload = {}
    return {
        "id": row.id,
        "title": row.title,
        "body": row.body,
        "kind": row.kind or "schedule",
        "payload": payload,
        "isRead": row.read_at is not None,
        "createdAt": row.created_at.isoformat() if row.created_at else "",
    }


def active_coverage_for_rotation(rotation: CallRotation) -> CallCoverage | None:
    for coverage in rotation.coverages or []:
        if coverage.status == "active":
            return coverage
    return None


def serialize_call_assignment(rotation: CallRotation, viewer_id: int) -> dict:
    coverage = active_coverage_for_rotation(rotation)
    original = rotation.surgeon
    covering = coverage.covering_surgeon if coverage else None
    active_surgeon = covering or original
    return {
        "rotationId": rotation.id,
        "groupId": rotation.call_group_id,
        "group": rotation.call_group.name if rotation.call_group else "Call",
        "surgeon": active_surgeon.full_name if active_surgeon else "No call",
        "surgeonId": active_surgeon.id if active_surgeon else None,
        "initials": active_surgeon.initials if active_surgeon else "NC",
        "isSelf": bool(active_surgeon and active_surgeon.id == viewer_id),
        "originalSurgeon": original.full_name if original else "No call",
        "originalSurgeonId": original.id if original else None,
        "originalInitials": original.initials if original else "NC",
        "coveringSurgeon": covering.full_name if covering else None,
        "coveringSurgeonId": covering.id if covering else None,
        "coveringInitials": covering.initials if covering else None,
        "isCovered": coverage is not None,
        "coverageId": coverage.id if coverage else None,
    }


def meetings_for_surgeon(db: Session, surgeon_id: int, start_date: date, end_date: date) -> list[Meeting]:
    return (
        db.query(Meeting)
        .outerjoin(MeetingAttendee)
        .filter(
            Meeting.date >= start_date,
            Meeting.date <= end_date,
            or_(
                MeetingAttendee.surgeon_id == surgeon_id,
                ~Meeting.attendees.any(),
            ),
        )
        .distinct()
        .order_by(Meeting.date, Meeting.start_time, Meeting.id)
        .all()
    )


def months_spanned(sd: date, ed: date) -> list[tuple[int, int]]:
    months = []
    cursor = date(sd.year, sd.month, 1)
    end_month = date(ed.year, ed.month, 1)
    while cursor <= end_month:
        months.append((cursor.year, cursor.month))
        year = cursor.year + (1 if cursor.month == 12 else 0)
        month = 1 if cursor.month == 12 else cursor.month + 1
        cursor = date(year, month, 1)
    return months


def native_viewer_sees_physicians(viewer: Surgeon) -> bool:
    return (viewer.staff_type or "").lower() == "physician"


def native_day_off_sections(db: Session, viewer: Surgeon) -> list[dict]:
    today = date.today()
    current_month = date(today.year, today.month, 1)
    window_start = current_month - timedelta(days=95)
    discovery_end = today + timedelta(days=730)
    rows = (
        db.query(DayOff)
        .join(Surgeon, DayOff.surgeon_id == Surgeon.id)
        .filter(
            DayOff.status != "denied",
            Surgeon.is_active == True,  # noqa: E712
            DayOff.start_date <= discovery_end,
            DayOff.end_date >= window_start,
        )
        .order_by(DayOff.start_date)
        .options(joinedload(DayOff.surgeon))
        .all()
    )
    months = []
    cursor = date(window_start.year, window_start.month, 1)
    for _ in range(16):
        months.append((cursor.year, cursor.month))
        year = cursor.year + (1 if cursor.month == 12 else 0)
        month = 1 if cursor.month == 12 else cursor.month + 1
        cursor = date(year, month, 1)
    for req in rows:
        ym = (req.start_date.year, req.start_date.month)
        if ym not in months and ym >= months[0]:
            months.append(ym)
    months.sort()

    target_staff_type = "physician" if native_viewer_sees_physicians(viewer) else "staff"
    header_suffix = "SURGEONS" if target_staff_type == "physician" else "PAS"
    by_month: dict[tuple[int, int], list[DayOff]] = defaultdict(list)
    for req in rows:
        if not req.surgeon:
            continue
        if target_staff_type == "physician" and req.surgeon.staff_type != "physician":
            continue
        if target_staff_type != "physician" and req.surgeon.staff_type == "physician":
            continue
        for ym in months_spanned(req.start_date, req.end_date):
            by_month[ym].append(req)
    for requests in by_month.values():
        requests.sort(key=lambda req: (native_surgeon_rank_key(req.surgeon), req.start_date, req.id))
    return [
        {
            "header": f"{date(y, m, 1).strftime('%b').upper()} {header_suffix}",
            "isCurrentMonth": y == today.year and m == today.month,
            "requests": [serialize_day_off(r) for r in by_month.get((y, m), [])],
        }
        for y, m in months
    ]
