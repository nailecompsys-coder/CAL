"""English formatters over the same queries the portal screens already run.

Do not parse questions here. The dispatcher in grok_ask_service fills slots,
then calls one of these. Secrets, OTP codes, magic links, and device tokens
are never in an answer.
"""
from __future__ import annotations

import re
from datetime import date, timedelta

from sqlalchemy.orm import Session, joinedload

from .admin_dashboard_stats_service import clinic_visits_today_count
from .grok_ask_intent import is_identity_question, is_when_question, location_needles
from .models import (
    AdminNotification,
    Availability,
    CallCoverage,
    CallGroup,
    CallRotation,
    ClinicGroup,
    ClinicSchedule,
    DayOff,
    Location,
    Meeting,
    MeetingAttendee,
    ORBlockAssignment,
    ORBlockInstance,
    Surgeon,
    SurgeonDayItem,
    SurgicalCase,
)
from .off_conflict_service import aprima_patient_counts, clinic_patient_count_for_schedules
from .practice_time import practice_now
from .surgeon_visibility import surgeon_is_visible

_SECRET_KINDS = frozenset({
    "otp", "magic_link", "device", "password", "token", "secret",
})

def _answer_when(text: str, today: date) -> dict:
    blob = text.lower()
    now = practice_now()
    if "tomorrow" in blob:
        day = today + timedelta(days=1)
        word = "Tomorrow"
    elif "yesterday" in blob:
        day = today - timedelta(days=1)
        word = "Yesterday"
    else:
        day = today
        word = "Today"
    pretty = f"{day.strftime('%A')}, {day.strftime('%B %-d, %Y')}"
    lines = [pretty]
    if re.search(r"\btime\b", blob) and "tomorrow" not in blob and "yesterday" not in blob:
        clock = now.strftime("%-I:%M %p").lstrip("0")
        lines = [f"It is {clock} Eastern.", pretty]
    return _talk(word, topic="when", lines=lines)


def _answer_identity() -> dict:
    return _talk(
        "I'm Grok-BOT",
        topic="identity",
        lines=[
            "Today's Coverage",
            "Surgical Cases Today",
            "Clinic Visits Today",
            "No Call Today",
            "Available Today",
            "Pending Approvals",
            "Meetings This Week",
            "Time Off, Block OR, and locations",
            "Nothing leaves the app.",
        ],
    )


def _answer_freeform(text: str, today: date) -> dict:
    blob = text.lower()
    if is_when_question(blob) or (
        re.search(r"\b(today|tomorrow|yesterday)\b", blob)
        and not re.search(r"\bwho\b", blob)
        and len(blob.split()) <= 8
    ):
        return _answer_when(text, today)
    if is_identity_question(blob):
        return _answer_identity()
    tomorrow = today + timedelta(days=1)
    return _talk(
        "I don't have that as a named person or place",
        topic="freeform",
        lines=[
            f"Today is {today.strftime('%A')}, {today.strftime('%B %-d, %Y')}",
            f"Tomorrow is {tomorrow.strftime('%A')}, {tomorrow.strftime('%B %-d, %Y')}",
            "Ask a Dashboard label: Today's Coverage, Surgical Cases Today, "
            "Clinic Visits Today, No Call Today, Available Today, Pending Approvals, "
            "or Meetings This Week — or name a doctor.",
        ],
    )


def collect_surgeon_facts(db: Session, surgeon: Surgeon, start: date, end: date) -> dict:
    off_days = _off_days(db, surgeon.id, start, end, "approved")
    pending_days = _off_days(db, surgeon.id, start, end, "pending")
    cases = (
        db.query(SurgicalCase)
        .options(joinedload(SurgicalCase.location))
        .filter(
            SurgicalCase.surgeon_id == surgeon.id,
            SurgicalCase.date >= start,
            SurgicalCase.date <= end,
            SurgicalCase.status != "cancelled",
        )
        .order_by(SurgicalCase.date, SurgicalCase.start_time)
        .all()
    )
    clinics = (
        db.query(ClinicSchedule)
        .options(joinedload(ClinicSchedule.location))
        .filter(
            ClinicSchedule.surgeon_id == surgeon.id,
            ClinicSchedule.date >= start,
            ClinicSchedule.date <= end,
        )
        .all()
    )
    fax_patients = clinic_patient_count_for_schedules(clinics)
    aprima = aprima_patient_counts(db, start, end, {surgeon.id: surgeon})
    aprima_patients = sum(aprima.values())
    rotations = (
        db.query(CallRotation)
        .options(joinedload(CallRotation.call_group), joinedload(CallRotation.coverages))
        .filter(
            CallRotation.surgeon_id == surgeon.id,
            CallRotation.date >= start,
            CallRotation.date <= end,
        )
        .all()
    )
    covering_rows = (
        db.query(CallCoverage)
        .options(joinedload(CallCoverage.rotation))
        .filter(
            CallCoverage.covering_surgeon_id == surgeon.id,
            CallCoverage.status == "active",
        )
        .all()
    )
    covering_days = [
        row.rotation.date
        for row in covering_rows
        if row.rotation and start <= row.rotation.date <= end
    ]
    meetings = (
        db.query(Meeting)
        .join(MeetingAttendee)
        .filter(
            MeetingAttendee.surgeon_id == surgeon.id,
            Meeting.date >= start,
            Meeting.date <= end,
        )
        .all()
    )
    blocks = (
        db.query(ORBlockAssignment)
        .join(ORBlockInstance)
        .options(joinedload(ORBlockAssignment.block_instance).joinedload(ORBlockInstance.location))
        .filter(
            ORBlockAssignment.surgeon_id == surgeon.id,
            ORBlockInstance.date >= start,
            ORBlockInstance.date <= end,
        )
        .all()
    )
    availability = (
        db.query(Availability)
        .filter(
            Availability.surgeon_id == surgeon.id,
            Availability.date >= start,
            Availability.date <= end,
        )
        .all()
    )
    day_items = (
        db.query(SurgeonDayItem)
        .filter(
            SurgeonDayItem.surgeon_id == surgeon.id,
            SurgeonDayItem.date >= start,
            SurgeonDayItem.date <= end,
        )
        .all()
    )
    return {
        "off_days": off_days,
        "pending_days": pending_days,
        "cases": cases,
        "clinic_days": [c for c in clinics if (c.assignment_type or "assigned").lower() != "off"],
        "fax_patients": fax_patients,
        "aprima_patients": aprima_patients,
        "call_days": [r.date for r in rotations if r.surgeon_id],
        "covering_days": covering_days,
        "meetings": meetings,
        "blocks": blocks,
        "availability": availability,
        "day_items": day_items,
    }


def _off_days(db: Session, surgeon_id: int, start: date, end: date, status: str) -> list[date]:
    rows = (
        db.query(DayOff)
        .filter(
            DayOff.surgeon_id == surgeon_id,
            DayOff.status == status,
            DayOff.start_date <= end,
            DayOff.end_date >= start,
        )
        .all()
    )
    days: set[date] = set()
    for row in rows:
        current = max(row.start_date, start)
        last = min(row.end_date, end)
        while current <= last:
            days.add(current)
            current += timedelta(days=1)
    return sorted(days)


def _answer_time_off(surgeon: Surgeon, window: dict, facts: dict) -> dict:
    n = len(facts["off_days"])
    pending = len(facts["pending_days"])
    lines = [
        f"{n} approved time-off day{'s' if n != 1 else ''} {window['label']}",
    ]
    if pending:
        lines.append(f"{pending} pending")
    return _talk(
        f"{surgeon.full_name} — time off",
        topic="time_off",
        lines=lines,
        count=n,
    )


def _answer_clinic(surgeon: Surgeon, window: dict, facts: dict) -> dict:
    aprima = facts["aprima_patients"]
    fax = facts["fax_patients"]
    if aprima:
        count, source = aprima, "Aprima"
    else:
        count, source = fax, "the clinic schedule"
    return _talk(
        f"{surgeon.full_name} — clinic",
        topic="clinic",
        lines=[
            f"{count} clinic patient{'' if count == 1 else 's'} {window['label']} ({source})",
        ],
        count=count,
    )


def _answer_cases(surgeon: Surgeon, window: dict, facts: dict) -> dict:
    n = len(facts["cases"])
    lines = [
        f"{n} surgical case{'s' if n != 1 else ''} {window['label']}",
    ]
    untimed = sum(1 for row in facts["cases"] if row.start_time is None)
    if untimed:
        lines.append(f"{untimed} still have no start time")
    return _talk(
        f"{surgeon.full_name} — cases",
        topic="cases",
        lines=lines,
        count=n,
    )


def _answer_call(surgeon: Surgeon, window: dict, facts: dict) -> dict:
    assigned = facts["call_days"]
    covering = facts["covering_days"]
    lines = []
    if assigned:
        lines.append("On call " + ", ".join(d.strftime("%b %-d") for d in assigned[:8]))
    if covering:
        lines.append("Covering " + ", ".join(d.strftime("%b %-d") for d in covering[:8]))
    if not lines:
        lines = [f"Not on call {window['label']}"]
    return _talk(
        f"{surgeon.full_name} — call",
        topic="call",
        lines=lines,
        count=len(assigned) + len(covering),
    )


def _answer_meetings(surgeon: Surgeon, window: dict, facts: dict) -> dict:
    rows = facts["meetings"]
    if not rows:
        return _talk(
            f"{surgeon.full_name} — meetings",
            topic="meetings",
            lines=[f"No meetings {window['label']}"],
            count=0,
        )
    return _talk(
        f"{surgeon.full_name} — {len(rows)} meeting{'' if len(rows) == 1 else 's'} {window['label']}",
        topic="meetings",
        lines=[_meeting_line(row) for row in rows],
    )


def _answer_meetings_board(db: Session, window: dict) -> dict:
    rows = (
        db.query(Meeting)
        .options(
            joinedload(Meeting.location),
            joinedload(Meeting.attendees).joinedload(MeetingAttendee.surgeon),
        )
        .filter(Meeting.date >= window["start"], Meeting.date <= window["end"])
        .order_by(Meeting.date, Meeting.start_time)
        .all()
    )
    if not rows:
        return _talk(
            "Meetings",
            topic="meetings",
            lines=[f"None on the board {window['label']}"],
            count=0,
        )
    lines = [_meeting_line(row) for row in rows]
    heading = (
        f"Meetings This Week ({len(rows)})"
        if "this week" in window["label"]
        else f"{len(rows)} meeting{'' if len(rows) == 1 else 's'} {window['label']}"
    )
    return _talk(heading, topic="meetings", lines=lines)


def _answer_cases_board(db: Session, window: dict) -> dict:
    rows = (
        db.query(SurgicalCase)
        .options(joinedload(SurgicalCase.surgeon), joinedload(SurgicalCase.location))
        .filter(
            SurgicalCase.date >= window["start"],
            SurgicalCase.date <= window["end"],
            SurgicalCase.status != "cancelled",
        )
        .order_by(SurgicalCase.date, SurgicalCase.start_time)
        .all()
    )
    if not rows:
        return _talk(
            "Surgical cases",
            topic="cases",
            lines=[f"None on the board {window['label']}"],
            count=0,
        )
    lines = []
    for row in rows[:40]:
        who = row.surgeon.full_name if row.surgeon else "unassigned"
        clock = _clock_label(row.start_time)
        loc = ""
        if row.location:
            loc = f" · {row.location.abbreviation or row.location.name}"
        lines.append(
            f"{row.date.strftime('%a %b %-d')} · {clock} · {who}{loc}"
            + (f" · {row.procedure}" if row.procedure else "")
        )
    heading = (
        f"Surgical Cases Today ({len(rows)})"
        if window["label"] == "today"
        else f"{len(rows)} surgical case{'' if len(rows) == 1 else 's'} {window['label']}"
    )
    return _talk(heading, topic="cases", lines=lines, count=len(rows))


def _answer_blocks_board(db: Session, window: dict) -> dict:
    rows = (
        db.query(ORBlockInstance)
        .options(
            joinedload(ORBlockInstance.location),
            joinedload(ORBlockInstance.assigned_surgeon),
            joinedload(ORBlockInstance.assignments).joinedload(ORBlockAssignment.surgeon),
        )
        .filter(
            ORBlockInstance.date >= window["start"],
            ORBlockInstance.date <= window["end"],
        )
        .order_by(ORBlockInstance.date, ORBlockInstance.start_time)
        .all()
    )
    if not rows:
        return _talk(
            "Block OR",
            topic="blocks",
            lines=[f"None on the board {window['label']}"],
            count=0,
        )
    lines = []
    for row in rows[:40]:
        loc = ""
        if row.location:
            loc = row.location.abbreviation or row.location.name
        who = ""
        if row.assigned_surgeon and surgeon_is_visible(row.assigned_surgeon):
            who = row.assigned_surgeon.full_name
        elif row.assignments:
            names = [
                a.surgeon.full_name
                for a in row.assignments
                if a.surgeon and surgeon_is_visible(a.surgeon)
            ]
            who = ", ".join(names[:4])
        lines.append(
            f"{row.date.strftime('%a %b %-d')} · {_clock_label(row.start_time)} · "
            f"{loc or 'OR'} · {who or (row.status or 'open')}"
        )
    heading = f"{len(rows)} Block OR row{'' if len(rows) == 1 else 's'} {window['label']}"
    return _talk(heading, topic="blocks", lines=lines, count=len(rows))


def _answer_locations_board(db: Session) -> dict:
    rows = (
        db.query(Location)
        .filter(Location.is_active.is_(True))
        .order_by(Location.name)
        .all()
    )
    if not rows:
        return _talk("Locations", topic="location", lines=["No active locations on file."], count=0)
    lines = []
    for row in rows:
        bits = [row.name]
        if row.abbreviation:
            bits.append(row.abbreviation)
        if row.location_type:
            bits.append(row.location_type)
        lines.append(" · ".join(bits))
    return _talk(f"{len(rows)} locations", topic="location", lines=lines, count=len(rows))


def _answer_board(db: Session, window: dict) -> dict:
    meetings = _answer_meetings_board(db, window)
    cases = _answer_cases_board(db, window)
    off = _answer_who_off(db, window)
    call = _answer_who_call(db, window)
    lines = (
        _prefixed("Meetings", meetings)
        + _prefixed("Cases", cases)
        + _prefixed("Out", off)
        + _prefixed("Coverage", call)
    )
    return _talk(f"Live board {window['label']}", topic="board", lines=lines)


def _meeting_line(row: Meeting) -> str:
    clock = _clock_label(row.start_time)
    loc = ""
    if row.location:
        loc = f" · {row.location.abbreviation or row.location.name}"
    elif row.location_text:
        loc = f" · {row.location_text}"
    who = []
    for att in row.attendees or []:
        if att.surgeon and surgeon_is_visible(att.surgeon):
            name = att.surgeon.full_name
            if name and name not in who:
                who.append(name)
    people = f" · {', '.join(who[:6])}" if who else ""
    return f"{row.date.strftime('%a %b %-d')} · {clock} · {row.title or 'Meeting'}{loc}{people}"


def _clock_label(value) -> str:
    if not value:
        return "time TBD"
    stamp = value.strftime("%I:%M %p")
    return stamp.lstrip("0")


def _plain(title: str, lines: list[str]) -> str:
    body = "\n".join(f"• {line}" for line in lines if line)
    if body:
        return f"{title}\n\n{body}"
    return title


def _bullet_lines(payload: dict) -> list[str]:
    if payload.get("title"):
        return [line for line in (payload.get("lines") or []) if line]
    raw = [line for line in (payload.get("lines") or []) if line]
    if len(raw) > 1:
        return raw[1:]
    answer = (payload.get("answer") or "").strip()
    return [answer] if answer else []


def _prefixed(prefix: str, payload: dict) -> list[str]:
    return [f"{prefix} · {line}" for line in _bullet_lines(payload)]


def _talk(
    title: str,
    *,
    topic: str,
    lines: list[str] | None = None,
    count: int | None = None,
    layout: str | None = None,
) -> dict:
    heading = title.rstrip(":").strip()
    items = [line for line in (lines or []) if line][:40]
    answer = _plain(heading, items)
    if layout is None:
        layout = "panel" if len(items) > 4 or len(answer) > 220 else "bubble"
    payload = {
        "ok": True,
        "topic": topic,
        "title": heading,
        "lines": items,
        "answer": answer,
        "layout": layout,
    }
    if count is not None:
        payload["count"] = count
    elif items:
        payload["count"] = len(items)
    return payload


def _talk_list(heading: str, lines: list[str], *, topic: str, count: int | None = None) -> dict:
    return _talk(heading, topic=topic, lines=lines, count=count)


def _answer_blocks(surgeon: Surgeon, window: dict, facts: dict) -> dict:
    n = len(facts["blocks"])
    return _talk(
        f"{surgeon.full_name} — Block OR",
        topic="blocks",
        lines=[
            f"{n} Block OR assignment{'s' if n != 1 else ''} {window['label']}",
        ],
        count=n,
    )


def _answer_availability(surgeon: Surgeon, window: dict, facts: dict) -> dict:
    n = len(facts["availability"]) + len(facts["day_items"])
    return _talk(
        f"{surgeon.full_name} — availability",
        topic="availability",
        lines=[
            f"{n} availability / personal item{'' if n == 1 else 's'} {window['label']}",
        ],
        count=n,
    )


def _answer_contact(surgeon: Surgeon) -> dict:
    lines = []
    if surgeon.phone:
        lines.append(surgeon.phone)
    if surgeon.email:
        lines.append(surgeon.email)
    if not lines:
        lines = ["no phone or email on file"]
    return _talk(surgeon.full_name, topic="contact", lines=lines)


def _answer_briefing(surgeon: Surgeon, window: dict, facts: dict) -> dict:
    clinic_n = facts["aprima_patients"] or facts["fax_patients"]
    places = []
    for row in facts["clinic_days"]:
        if row.location:
            label = row.location.abbreviation or row.location.name
            if label and label not in places:
                places.append(label)
    loc_bit = f" at {', '.join(places[:4])}" if places else ""
    return _talk(
        f"{surgeon.full_name} — {window['label']}",
        topic="briefing",
        lines=[
            f"{len(facts['off_days'])} time-off days",
            f"{clinic_n} clinic patients{loc_bit}",
            f"{len(facts['cases'])} surgical cases",
            f"{len(facts['call_days'])} call days",
            f"{len(facts['meetings'])} meetings",
            f"{len(facts['blocks'])} Block OR assignments",
        ],
    )


def _answer_who_off(db: Session, window: dict) -> dict:
    out_names, _no_call = _off_lists_for_window(db, window)
    heading = "Out Today" if window["label"] == "today" else f"Out {window['label']}"
    if not out_names:
        return _talk(heading, topic="who_off", lines=["Nobody is out."], count=0)
    return _talk(
        f"{heading} ({len(out_names)})",
        topic="who_off",
        lines=out_names,
        count=len(out_names),
    )


def _answer_pending_off(
    db: Session,
    window: dict,
    *,
    today: date | None = None,
) -> dict:
    cutoff = today or window["start"]
    rows = (
        db.query(DayOff)
        .options(joinedload(DayOff.surgeon))
        .filter(
            DayOff.status == "pending",
            DayOff.end_date >= cutoff,
        )
        .order_by(DayOff.created_at.asc().nullsfirst(), DayOff.id.asc())
        .all()
    )
    names = []
    for row in rows:
        if not surgeon_is_visible(row.surgeon):
            continue
        label = row.surgeon.full_name
        if label not in names:
            names.append(label)
    if not names:
        return _talk("Pending Approvals", topic="pending_off", lines=["All clear."], count=0)
    return _talk(
        f"Pending Approvals ({len(names)})",
        topic="pending_off",
        lines=names,
        count=len(names),
    )


def _is_no_call_reason(reason: str | None) -> bool:
    if not reason:
        return False
    return " ".join(reason.strip().lower().split()) == "no call"


def _off_lists_for_window(db: Session, window: dict) -> tuple[list[str], list[str]]:
    rows = (
        db.query(DayOff)
        .options(joinedload(DayOff.surgeon))
        .filter(
            DayOff.start_date <= window["end"],
            DayOff.end_date >= window["start"],
            DayOff.status == "approved",
        )
        .all()
    )
    out_names: list[str] = []
    no_call_names: list[str] = []
    for row in rows:
        if not surgeon_is_visible(row.surgeon):
            continue
        name = row.surgeon.full_name
        if _is_no_call_reason(row.reason):
            if name not in no_call_names:
                no_call_names.append(name)
        elif name not in out_names:
            out_names.append(name)
    return out_names, no_call_names


def _answer_who_call(db: Session, window: dict) -> dict:
    """Same facts as the dashboard Today's Coverage card."""
    rows = (
        db.query(CallRotation)
        .options(
            joinedload(CallRotation.surgeon),
            joinedload(CallRotation.call_group),
            joinedload(CallRotation.coverages).joinedload(CallCoverage.covering_surgeon),
        )
        .filter(CallRotation.date >= window["start"], CallRotation.date <= window["end"])
        .order_by(CallRotation.date)
        .all()
    )
    lines = []
    for row in rows:
        if not row.surgeon_id or not surgeon_is_visible(row.surgeon):
            continue
        group = row.call_group.name if row.call_group else "On-Call"
        stamp = ""
        if window["start"] != window["end"]:
            stamp = f"{row.date.strftime('%a %b %-d')} · "
        extra = ""
        active = row.active_coverage
        if active:
            covering = active.covering_surgeon or db.get(Surgeon, active.covering_surgeon_id)
            if covering and surgeon_is_visible(covering):
                extra = f" · covering: {covering.full_name}"
        lines.append(f"{stamp}{row.surgeon.full_name} · {group}{extra}")

    heading = (
        "Today's Coverage"
        if window["label"] == "today"
        else f"Coverage {window['label']}"
    )
    if not lines:
        lines = [
            "No On-Call Coverage — not assigned."
            if window["label"] == "today"
            else f"No On-Call Coverage {window['label']}."
        ]

    if window["start"] == window["end"]:
        out_names, no_call_names = _off_lists_for_window(db, window)
        for name in out_names[:12]:
            lines.append(f"Out · {name}")
        for name in no_call_names[:12]:
            lines.append(f"No Call · {name}")

    return _talk(heading, topic="who_call", lines=lines, count=len(lines))


def _answer_no_call(db: Session, window: dict) -> dict:
    _out_names, no_call_names = _off_lists_for_window(db, window)
    heading = "No Call Today" if window["label"] == "today" else f"No Call {window['label']}"
    if not no_call_names:
        return _talk(heading, topic="no_call", lines=["Nobody is marked No Call."], count=0)
    return _talk(
        f"{heading} ({len(no_call_names)})",
        topic="no_call",
        lines=no_call_names,
        count=len(no_call_names),
    )


def _answer_clinic_visits(db: Session, window: dict) -> dict:
    total = 0
    day = window["start"]
    while day <= window["end"]:
        total += clinic_visits_today_count(db, day)
        day += timedelta(days=1)
    heading = (
        "Clinic Visits Today"
        if window["label"] == "today"
        else f"Clinic Visits {window['label']}"
    )
    return _talk(heading, topic="clinic_visits", lines=[str(total)], count=total)


def _answer_available(db: Session, window: dict) -> dict:
    active = [
        row
        for row in db.query(Surgeon).filter(Surgeon.is_active.is_(True)).all()
        if surgeon_is_visible(row)
    ]
    out_names, _no_call = _off_lists_for_window(db, window)
    n = max(0, len(active) - len(out_names))
    heading = (
        "Available Today"
        if window["label"] == "today"
        else f"Available {window['label']}"
    )
    lines = [f"{n} / {len(active)} physicians in"]
    for name in out_names[:12]:
        lines.append(f"Out · {name}")
    return _talk(heading, topic="available", lines=lines, count=n)


def _answer_clinics_or(db: Session, window: dict) -> dict:
    clinic = _answer_who_clinic(db, window)
    cases = _answer_cases_board(db, window)
    lines = _prefixed("Clinic", clinic) + _prefixed("OR", cases)
    return _talk("Clinics / OR", topic="clinics_or", lines=lines)


def _answer_who_clinic(db: Session, window: dict) -> dict:
    rows = (
        db.query(ClinicSchedule)
        .options(joinedload(ClinicSchedule.surgeon), joinedload(ClinicSchedule.location))
        .filter(
            ClinicSchedule.date >= window["start"],
            ClinicSchedule.date <= window["end"],
        )
        .all()
    )
    bits = []
    for row in rows:
        if (row.assignment_type or "assigned").lower() == "off":
            continue
        if not surgeon_is_visible(row.surgeon):
            continue
        loc = ""
        if row.location:
            loc = f" at {row.location.abbreviation or row.location.name}"
        bits.append(f"{row.surgeon.full_name}{loc} {row.date.strftime('%b %-d')}")
    heading = f"Clinic {window['label']}"
    if not bits:
        return _talk(heading, topic="who_clinic", lines=["Nobody is in clinic."], count=0)
    return _talk(heading, topic="who_clinic", lines=bits[:20], count=len(bits))


def _answer_location_details(loc: Location) -> dict:
    lines = []
    if loc.abbreviation:
        lines.append(loc.abbreviation)
    if loc.phone:
        lines.append(loc.phone)
    addr = " ".join(part for part in (loc.address, loc.city) if part)
    if addr:
        lines.append(addr)
    if loc.location_type:
        lines.append(loc.location_type)
    if not lines:
        lines = ["on file"]
    return _talk(loc.name or "Location", topic="location", lines=lines)



def _aprima_clinic_count_at_location(
    db: Session,
    loc: Location,
    start: date,
    end: date,
) -> int:
    try:
        from .aprima_cache_service import patient_appointments_for_api
        from .aprima_schedule_service import is_surgery_appointment
    except Exception:
        return 0
    try:
        payload = patient_appointments_for_api(db, start, end, surgeon=None)
    except Exception:
        return 0
    needles = [n for n in location_needles(loc) if len(n) >= 4]
    if not needles:
        return 0
    total = 0
    for row in payload.get("appointments") or []:
        if is_surgery_appointment(row):
            continue
        day_raw = (row.get("date") or "")[:10]
        try:
            day = date.fromisoformat(day_raw)
        except ValueError:
            continue
        if day < start or day > end:
            continue
        site = (row.get("serviceSite") or "").strip().lower()
        if any(needle in site for needle in needles):
            total += 1
    return total


def _answer_location_volume(db: Session, loc: Location, window: dict, topic: str) -> dict:
    cases = (
        db.query(SurgicalCase)
        .filter(
            SurgicalCase.location_id == loc.id,
            SurgicalCase.date >= window["start"],
            SurgicalCase.date <= window["end"],
            SurgicalCase.status != "cancelled",
        )
        .all()
    )
    clinics = (
        db.query(ClinicSchedule)
        .filter(
            ClinicSchedule.location_id == loc.id,
            ClinicSchedule.date >= window["start"],
            ClinicSchedule.date <= window["end"],
        )
        .all()
    )
    patients = clinic_patient_count_for_schedules(clinics)
    patients += _aprima_clinic_count_at_location(db, loc, window["start"], window["end"])
    label = loc.name or loc.abbreviation or "that office"
    if topic == "clinic":
        if not patients:
            return _talk(
                f"{label} {window['label']}",
                topic="clinic",
                lines=["No patients are on the board."],
                count=0,
            )
        return _talk(
            f"{label} {window['label']}",
            topic="clinic",
            lines=[
                f"{patients} patient{'' if patients == 1 else 's'} to be seen",
            ],
            count=patients,
        )
    if topic == "cases":
        n = len(cases)
        return _talk(
            f"{label} {window['label']}",
            topic="cases",
            lines=[f"{n} surgical case{'s' if n != 1 else ''}"],
            count=n,
        )
    return _talk(
        f"{label} {window['label']}",
        topic="briefing",
        lines=[
            f"{patients} clinic patients",
            f"{len(cases)} surgical cases",
        ],
    )


def _answer_roster(db: Session) -> dict:
    rows = (
        db.query(Surgeon)
        .filter(Surgeon.is_active.is_(True))
        .order_by(Surgeon.last_name, Surgeon.first_name)
        .all()
    )
    names = [row.full_name for row in rows if surgeon_is_visible(row)]
    if not names:
        return _talk("Physicians", topic="roster", lines=["No active surgeons on file."], count=0)
    return _talk(f"{len(names)} physicians", topic="roster", lines=names[:40], count=len(names))


def _answer_groups(db: Session) -> dict:
    call_groups = [row.name for row in db.query(CallGroup).order_by(CallGroup.sort_order).all() if row.name]
    clinic_groups = [
        row.name
        for row in db.query(ClinicGroup).filter(ClinicGroup.is_active.is_(True)).all()
        if row.name
    ]
    lines = [f"Call · {name}" for name in call_groups[:20]]
    lines.extend(f"Clinic · {name}" for name in clinic_groups[:20])
    if not lines:
        return _talk("Groups", topic="groups", lines=["No call or clinic groups on file."])
    return _talk("Groups", topic="groups", lines=lines)


def _answer_notices(db: Session, admin_user_id: int | None) -> dict:
    q = db.query(AdminNotification).filter(AdminNotification.read_at.is_(None))
    if admin_user_id is not None:
        q = q.filter(AdminNotification.admin_user_id == admin_user_id)
    rows = q.order_by(AdminNotification.created_at.desc()).limit(30).all()
    titles = []
    for row in rows:
        kind = (row.kind or "").lower()
        if any(token in kind for token in _SECRET_KINDS):
            continue
        title = (row.title or "").strip()
        if title and title not in titles:
            titles.append(title)
    if not titles:
        return _talk("Admin Notifications", topic="notices", lines=["None unread."], count=0)
    return _talk(
        f"Admin Notifications ({len(titles)})",
        topic="notices",
        lines=titles[:12],
        count=len(titles),
    )


