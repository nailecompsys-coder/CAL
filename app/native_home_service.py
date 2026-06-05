"""Service builder for the native iOS home payload."""
from datetime import date, timedelta

from sqlalchemy.orm import Session, joinedload

from .models import (
    Availability,
    CallGroup,
    CallCoverage,
    CallRotation,
    ClinicSchedule,
    DayOff,
    Surgeon,
    SurgeonDayItem,
    SurgicalCase,
)
from .native_support import (
    active_coverage_for_rotation,
    date_label,
    fmt_time,
    meetings_for_surgeon,
    native_day_off_sections,
    native_surgeon_rank_key,
    parse_hhmm,
    segment_for_date,
    serialize_day_off,
    session_times,
)
from .native_home_sections import build_native_call_schedule, native_alerts


class NativeHomeService:
    def __init__(self, db: Session, surgeon: Surgeon, start_date: date, end_date: date):
        self.db = db
        self.surgeon = surgeon
        self.start_date = start_date
        self.end_date = end_date
        self.today = date.today()
        self.days = self._empty_days()
        self.by_date = {d["date"]: d for d in self.days}
        self.my_day_off_rows = self._my_day_off_rows()

    def build(self) -> dict:
        self._append_my_call_items()
        self._append_my_day_off_items()
        self._append_meetings()
        self._append_clinic_items()
        self._append_surgical_items()
        self._append_personal_items()
        self._sort_day_items()

        availability = self._availability()
        requests = self._requests()
        call_groups = self._call_groups()
        call_schedule = build_native_call_schedule(self.db, self.surgeon, self.start_date, self.end_date, self.by_date)
        alerts = native_alerts(self.db, self.surgeon)

        return {
            "surgeon": {"id": self.surgeon.id, "name": self.surgeon.full_name, "staffType": self.surgeon.staff_type},
            "range": {"start": self.start_date.isoformat(), "end": self.end_date.isoformat()},
            "days": self.days,
            "availability": availability,
            "requests": requests,
            "dayOffSections": native_day_off_sections(self.db, self.surgeon),
            "callGroups": [{"id": g.id, "name": g.name} for g in call_groups],
            "surgeons": self._surgeons(),
            "callSchedule": call_schedule,
            "alerts": alerts,
        }

    def _empty_days(self) -> list[dict]:
        days = []
        current = self.start_date
        while current <= self.end_date:
            days.append({
                **date_label(current),
                "items": [],
                "offSurgeons": [],
                "requestedOffSurgeons": [],
                "callAssignments": [],
            })
            current += timedelta(days=1)
        return days

    def _my_day_off_rows(self) -> list[DayOff]:
        return self.db.query(DayOff).filter(
            DayOff.surgeon_id == self.surgeon.id,
            DayOff.start_date <= self.end_date,
            DayOff.end_date >= self.start_date,
            DayOff.status.in_(["pending", "approved"]),
        ).all()

    def _blocked_by_my_day_off(self, item_date: date, start_t: str | None = None, end_t: str | None = None) -> bool:
        for off in self.my_day_off_rows:
            if off.start_date <= item_date <= off.end_date:
                segment = segment_for_date(off, item_date)
                if segment and segment.get("isFullDay"):
                    return True
                seg_start = parse_hhmm(segment.get("start")) if segment else off.start_time
                seg_end = parse_hhmm(segment.get("end")) if segment else off.end_time
                if not seg_start or not seg_end:
                    return True
                if not start_t:
                    return True
                item_start = parse_hhmm(start_t)
                item_end = parse_hhmm(end_t) or item_start
                if item_start and item_end and item_start < seg_end and item_end > seg_start:
                    return True
        return False

    def _append_my_call_items(self) -> None:
        for rotation in self.db.query(CallRotation).options(
            joinedload(CallRotation.call_group),
            joinedload(CallRotation.coverages).joinedload(CallCoverage.covering_surgeon),
            joinedload(CallRotation.surgeon),
        ).filter(
            CallRotation.date >= self.start_date,
            CallRotation.date <= self.end_date,
        ).all():
            coverage = active_coverage_for_rotation(rotation)
            if rotation.surgeon_id == self.surgeon.id or (coverage and coverage.covering_surgeon_id == self.surgeon.id):
                self.by_date[rotation.date.isoformat()]["items"].append({
                    "id": f"rot-{rotation.id}",
                    "rawId": rotation.id,
                    "type": "oncall",
                    "title": "On-Call Coverage" if coverage and coverage.covering_surgeon_id == self.surgeon.id else "On-Call",
                    "subtitle": rotation.call_group.name if rotation.call_group else "",
                    "allDay": True,
                })

    def _append_my_day_off_items(self) -> None:
        for row in self.my_day_off_rows:
            span = max(row.start_date, self.start_date)
            span_end = min(row.end_date, self.end_date)
            while span <= span_end:
                segment = segment_for_date(row, span) or {}
                is_full = segment.get("isFullDay", row.is_full_day if row.is_full_day is not None else True)
                self.by_date[span.isoformat()]["items"].append({
                    "id": f"off-{row.id}-{span.isoformat()}",
                    "type": "dayoff",
                    "title": "Day Off",
                    "subtitle": f"{row.reason or ''}{' · pending' if row.status == 'pending' else ''}".strip(" ·"),
                    "start": None if is_full else segment.get("start") or fmt_time(row.start_time),
                    "end": None if is_full else segment.get("end") or fmt_time(row.end_time),
                    "allDay": is_full,
                })
                span += timedelta(days=1)

    def _append_meetings(self) -> None:
        for meeting in meetings_for_surgeon(self.db, self.surgeon.id, self.start_date, self.end_date):
            self.by_date[meeting.date.isoformat()]["items"].append({
                "id": f"mtg-{meeting.id}",
                "type": "meeting",
                "title": meeting.title,
                "subtitle": meeting.location_text or "",
                "start": fmt_time(meeting.start_time),
                "end": fmt_time(meeting.end_time),
                "notes": meeting.notes or "",
            })

    def _append_clinic_items(self) -> None:
        for row in self.db.query(ClinicSchedule).options(joinedload(ClinicSchedule.location)).filter(
            ClinicSchedule.surgeon_id == self.surgeon.id,
            ClinicSchedule.date >= self.start_date,
            ClinicSchedule.date <= self.end_date,
        ).order_by(ClinicSchedule.date, ClinicSchedule.session, ClinicSchedule.id).all():
            start_t, end_t = session_times(row.session)
            if self._blocked_by_my_day_off(row.date, start_t, end_t):
                continue
            title = "OFF" if (row.assignment_type or "assigned") == "off" else (row.location.name if row.location else "Clinic")
            self.by_date[row.date.isoformat()]["items"].append({
                "id": f"clinic-{row.id}",
                "type": "clinic",
                "title": title,
                "subtitle": (row.session or "full").upper(),
                "start": start_t,
                "end": end_t,
                "color": "#cbd5e1" if title == "OFF" else ((row.location.color if row.location else None) or "#0ea5e9"),
                "notes": row.notes or "",
            })

    def _append_surgical_items(self) -> None:
        for row in self.db.query(SurgicalCase).options(joinedload(SurgicalCase.location)).filter(
            SurgicalCase.surgeon_id == self.surgeon.id,
            SurgicalCase.date >= self.start_date,
            SurgicalCase.date <= self.end_date,
            SurgicalCase.status != "cancelled",
        ).order_by(SurgicalCase.date, SurgicalCase.start_time, SurgicalCase.id).all():
            if self._blocked_by_my_day_off(row.date, fmt_time(row.start_time), fmt_time(row.end_time)):
                continue
            self.by_date[row.date.isoformat()]["items"].append({
                "id": f"surg-{row.id}",
                "rawId": row.id,
                "type": "surgery",
                "title": row.patient_name or "Surgery",
                "subtitle": row.procedure or "",
                "start": fmt_time(row.start_time) or "08:00",
                "end": fmt_time(row.end_time),
                "location": (row.location.name if row.location else "") or row.room_text or "",
                "room": row.room_text or "",
                "status": row.status or "scheduled",
                "notes": row.notes or "",
                "surgeonNotes": row.surgeon_notes or "",
                "color": (row.location.color if row.location else None) or "#e0f2fe",
            })

    def _append_personal_items(self) -> None:
        for row in self.db.query(SurgeonDayItem).filter(
            SurgeonDayItem.surgeon_id == self.surgeon.id,
            SurgeonDayItem.date >= self.start_date,
            SurgeonDayItem.date <= self.end_date,
        ).order_by(SurgeonDayItem.date, SurgeonDayItem.sort_order, SurgeonDayItem.id).all():
            self.by_date[row.date.isoformat()]["items"].append({
                "id": f"personal-{row.id}",
                "rawId": row.id,
                "type": "personal",
                "title": row.title,
                "subtitle": row.notes or "",
                "start": fmt_time(row.start_time),
                "end": fmt_time(row.end_time),
                "notes": row.notes or "",
            })

    def _sort_day_items(self) -> None:
        for day in self.days:
            day["items"].sort(key=lambda item: (item.get("start") or "99:99", item["type"], item["title"]))

    def _availability(self) -> list[dict]:
        avail_records = self.db.query(Availability).filter(
            Availability.surgeon_id == self.surgeon.id,
            Availability.date >= self.today,
            Availability.date <= self.today + timedelta(days=27),
        ).order_by(Availability.date).all()
        avail_map = {a.date: a for a in avail_records}
        availability = []
        for i in range(28):
            d = self.today + timedelta(days=i)
            rec = avail_map.get(d)
            availability.append({
                **date_label(d),
                "isAvailable": rec.is_available if rec else True,
                "start": fmt_time(rec.start_time) if rec else None,
                "end": fmt_time(rec.end_time) if rec else None,
            })
        return availability

    def _requests(self) -> list[dict]:
        return [
            serialize_day_off(row)
            for row in self.db.query(DayOff).filter(
                DayOff.surgeon_id == self.surgeon.id,
                DayOff.end_date >= self.today - timedelta(days=30),
            ).order_by(DayOff.start_date.desc(), DayOff.id.desc()).limit(50).all()
        ]

    def _call_groups(self) -> list[CallGroup]:
        return self.db.query(CallGroup).order_by(CallGroup.sort_order, CallGroup.name, CallGroup.id).all()

    def _surgeons(self) -> list[dict]:
        return [
            {"id": row.id, "name": row.full_name, "initials": row.initials, "staffType": row.staff_type, "sortOrder": row.sort_order or 0}
            for row in sorted(
                self.db.query(Surgeon).filter(Surgeon.is_active == True).all(),  # noqa: E712
                key=native_surgeon_rank_key,
            )
        ]

def build_native_home(db: Session, surgeon: Surgeon, start_date: date, end_date: date) -> dict:
    return NativeHomeService(db, surgeon, start_date, end_date).build()
