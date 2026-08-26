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
    if re.search(r"\btime\b", blob) and "tomorrow" not in blob and "yesterday" not in blob:
        clock = now.strftime("%-I:%M %p").lstrip("0")
        return {
            "ok": True,
            "topic": "when",
            "answer": f"It is {clock} Eastern. Today is {pretty}.",
        }
    return {
        "ok": True,
        "topic": "when",
        "answer": f"{word} is {pretty}.",
    }


def _answer_identity() -> dict:
    return {
        "ok": True,
        "topic": "identity",
        "answer": (
            "I'm Grok-BOT. I answer from the live CAL screens: Today's Coverage, "
            "Surgical Cases Today, Clinic Visits Today, No Call Today, Available Today, "
            "Pending Approvals, Meetings This Week, Time Off, Block OR, and locations. "
            "Nothing leaves the app."
        ),
    }


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
    return {
        "ok": True,
        "topic": "freeform",
        "layout": "bubble",
        "answer": (
            f"I don't have that as a named person or place. "
            f"Today is {today.strftime('%A')}, {today.strftime('%B %-d, %Y')}; "
            f"tomorrow is {tomorrow.strftime('%A')}, {tomorrow.strftime('%B %-d, %Y')}. "
            "Ask me a Dashboard label: Today's Coverage, Surgical Cases Today, "
            "Clinic Visits Today, No Call Today, Available Today, Pending Approvals, "
            "or Meetings This Week — or name a doctor."
        ),
    }


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
    extra = f" Plus {pending} pending." if pending else ""
    return {
        "ok": True,
        "topic": "time_off",
        "answer": (
            f"{surgeon.full_name} had {n} approved time-off "
            f"day{'s' if n != 1 else ''} {window['label']}.{extra}"
        ),
        "count": n,
    }


def _answer_clinic(surgeon: Surgeon, window: dict, facts: dict) -> dict:
    aprima = facts["aprima_patients"]
    fax = facts["fax_patients"]
    if aprima:
        count, source = aprima, "Aprima"
    else:
        count, source = fax, "the clinic schedule"
    return {
        "ok": True,
        "topic": "clinic",
        "answer": (
            f"{surgeon.full_name} had {count} clinic patient"
            f"{'' if count == 1 else 's'} {window['label']} ({source})."
        ),
        "count": count,
    }


def _answer_cases(surgeon: Surgeon, window: dict, facts: dict) -> dict:
    n = len(facts["cases"])
    untimed = sum(1 for row in facts["cases"] if row.start_time is None)
    extra = f" {untimed} still have no start time." if untimed else ""
    return {
        "ok": True,
        "topic": "cases",
        "answer": (
            f"{surgeon.full_name} had {n} surgical case{'s' if n != 1 else ''} "
            f"{window['label']}.{extra}"
        ),
        "count": n,
    }


def _answer_call(surgeon: Surgeon, window: dict, facts: dict) -> dict:
    assigned = facts["call_days"]
    covering = facts["covering_days"]
    bits = []
    if assigned:
        bits.append(f"on call {', '.join(d.strftime('%b %-d') for d in assigned[:8])}")
    if covering:
        bits.append(f"covering {', '.join(d.strftime('%b %-d') for d in covering[:8])}")
    if not bits:
        return {
            "ok": True,
            "topic": "call",
            "answer": f"{surgeon.full_name} is not on call {window['label']}.",
            "count": 0,
        }
    return {
        "ok": True,
        "topic": "call",
        "answer": f"{surgeon.full_name} is {' and '.join(bits)} {window['label']}.",
        "count": len(assigned) + len(covering),
    }


def _answer_meetings(surgeon: Surgeon, window: dict, facts: dict) -> dict:
    rows = facts["meetings"]
    if not rows:
        return _talk(
            f"{surgeon.full_name} has no meetings {window['label']}.",
            topic="meetings",
            count=0,
        )
    lines = [_meeting_line(row) for row in rows]
    heading = (
        f"{surgeon.full_name} has {len(rows)} meeting"
        f"{'' if len(rows) == 1 else 's'} {window['label']}:"
    )
    return _talk_list(heading, lines, topic="meetings")


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
            f"No meetings are on the board {window['label']}.",
            topic="meetings",
            count=0,
        )
    lines = [_meeting_line(row) for row in rows]
    heading = (
        f"Meetings This Week ({len(rows)}):"
        if "this week" in window["label"]
        else f"{len(rows)} meeting{'' if len(rows) == 1 else 's'} {window['label']}:"
    )
    return _talk_list(heading, lines, topic="meetings")


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
            f"No surgical cases are on the board {window['label']}.",
            topic="cases",
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
        f"Surgical Cases Today ({len(rows)}):"
        if window["label"] == "today"
        else f"{len(rows)} surgical case{'' if len(rows) == 1 else 's'} {window['label']}:"
    )
    return _talk_list(heading, lines, topic="cases", count=len(rows))


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
            f"No Block OR rows are on the board {window['label']}.",
            topic="blocks",
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
    heading = f"{len(rows)} Block OR row{'' if len(rows) == 1 else 's'} {window['label']}:"
    return _talk_list(heading, lines, topic="blocks", count=len(rows))


def _answer_locations_board(db: Session) -> dict:
    rows = (
        db.query(Location)
        .filter(Location.is_active.is_(True))
        .order_by(Location.name)
        .all()
    )
    if not rows:
        return _talk("No active locations on file.", topic="location", count=0)
    lines = []
    for row in rows:
        bits = [row.name]
        if row.abbreviation:
            bits.append(row.abbreviation)
        if row.location_type:
            bits.append(row.location_type)
        lines.append(" · ".join(bits))
    heading = f"{len(rows)} locations:"
    return _talk_list(heading, lines, topic="location", count=len(rows))


def _answer_board(db: Session, window: dict) -> dict:
    meetings = _answer_meetings_board(db, window)
    cases = _answer_cases_board(db, window)
    off = _answer_who_off(db, window)
    call = _answer_who_call(db, window)
    lines = [
        f"Live board {window['label']}:",
        meetings.get("answer") or "",
        cases.get("answer") or "",
        off.get("answer") or "",
        call.get("answer") or "",
    ]
    clean = [line for line in lines if line]
    return _talk_list(clean[0], clean[1:], topic="board")


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


def _talk(answer: str, *, topic: str, count: int | None = None, layout: str = "bubble") -> dict:
    payload = {"ok": True, "topic": topic, "answer": answer, "layout": layout}
    if count is not None:
        payload["count"] = count
    return payload


def _talk_list(heading: str, lines: list[str], *, topic: str, count: int | None = None) -> dict:
    shown = lines[:40]
    answer = heading + "\n" + "\n".join(shown)
    layout = "panel" if len(shown) > 4 or len(answer) > 220 else "bubble"
    payload = {
        "ok": True,
        "topic": topic,
        "answer": answer,
        "lines": [heading] + shown,
        "layout": layout,
        "count": len(lines) if count is None else count,
    }
    return payload


def _answer_blocks(surgeon: Surgeon, window: dict, facts: dict) -> dict:
    n = len(facts["blocks"])
    return {
        "ok": True,
        "topic": "blocks",
        "answer": (
            f"{surgeon.full_name} has {n} Block OR assignment"
            f"{'s' if n != 1 else ''} {window['label']}."
        ),
        "count": n,
    }


def _answer_availability(surgeon: Surgeon, window: dict, facts: dict) -> dict:
    n = len(facts["availability"]) + len(facts["day_items"])
    return {
        "ok": True,
        "topic": "availability",
        "answer": (
            f"{surgeon.full_name} has {n} availability / personal item"
            f"{'' if n == 1 else 's'} {window['label']}."
        ),
        "count": n,
    }


def _answer_contact(surgeon: Surgeon) -> dict:
    bits = [surgeon.full_name]
    if surgeon.phone:
        bits.append(surgeon.phone)
    if surgeon.email:
        bits.append(surgeon.email)
    if len(bits) == 1:
        bits.append("no phone or email on file")
    return {"ok": True, "topic": "contact", "answer": " · ".join(bits) + "."}


def _answer_briefing(surgeon: Surgeon, window: dict, facts: dict) -> dict:
    clinic_n = facts["aprima_patients"] or facts["fax_patients"]
    places = []
    for row in facts["clinic_days"]:
        if row.location:
            label = row.location.abbreviation or row.location.name
            if label and label not in places:
                places.append(label)
    loc_bit = f" at {', '.join(places[:4])}" if places else ""
    parts = [
        f"{len(facts['off_days'])} time-off days",
        f"{clinic_n} clinic patients{loc_bit}",
        f"{len(facts['cases'])} surgical cases",
        f"{len(facts['call_days'])} call days",
        f"{len(facts['meetings'])} meetings",
        f"{len(facts['blocks'])} Block OR assignments",
    ]
    return {
        "ok": True,
        "topic": "briefing",
        "answer": f"{surgeon.full_name} {window['label']}: " + "; ".join(parts) + ".",
    }


def _answer_who_off(db: Session, window: dict) -> dict:
    out_names, _no_call = _off_lists_for_window(db, window)
    if not out_names:
        heading = "Out Today" if window["label"] == "today" else f"Out {window['label']}"
        return _talk(f"Nobody is {heading.lower()}.", topic="who_off", count=0)
    heading = (
        f"Out Today ({len(out_names)}):"
        if window["label"] == "today"
        else f"Out {window['label']} ({len(out_names)}):"
    )
    return _talk_list(heading, out_names, topic="who_off", count=len(out_names))


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
        return _talk("Pending Approvals: all clear.", topic="pending_off", count=0)
    return _talk_list(
        f"Pending Approvals ({len(names)}):",
        names,
        topic="pending_off",
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
        "Today's Coverage:"
        if window["label"] == "today"
        else f"Coverage {window['label']}:"
    )
    if not lines:
        lines = [
            "No On-Call Coverage — not assigned."
            if window["label"] == "today"
            else f"No On-Call Coverage {window['label']}."
        ]

    if window["start"] == window["end"]:
        out_names, no_call_names = _off_lists_for_window(db, window)
        if out_names:
            lines.append("Out today: " + ", ".join(out_names[:12]))
        if no_call_names:
            lines.append("No Call Today: " + ", ".join(no_call_names[:12]))

    return _talk_list(heading, lines, topic="who_call", count=len(lines))


def _answer_no_call(db: Session, window: dict) -> dict:
    _out_names, no_call_names = _off_lists_for_window(db, window)
    if not no_call_names:
        return _talk(f"Nobody is marked No Call {window['label']}.", topic="no_call", count=0)
    heading = f"No Call Today ({len(no_call_names)}):" if window["label"] == "today" else (
        f"No Call {window['label']} ({len(no_call_names)}):"
    )
    return _talk_list(heading, no_call_names, topic="no_call", count=len(no_call_names))


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
    return _talk(f"{heading}: {total}.", topic="clinic_visits", count=total)


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
    if out_names:
        lines.append("Out today: " + ", ".join(out_names[:12]))
    return _talk_list(f"{heading}:", lines, topic="available", count=n)


def _answer_clinics_or(db: Session, window: dict) -> dict:
    clinic = _answer_who_clinic(db, window)
    cases = _answer_cases_board(db, window)
    lines = [clinic.get("answer") or "", cases.get("answer") or ""]
    clean = [line for line in lines if line]
    return _talk_list("Clinics / OR:", clean, topic="clinics_or")


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
    if not bits:
        return {"ok": True, "topic": "who_clinic", "answer": f"Nobody is in clinic {window['label']}."}
    return {
        "ok": True,
        "topic": "who_clinic",
        "answer": f"Clinic {window['label']}: " + "; ".join(bits[:20]) + ".",
        "count": len(bits),
    }


def _answer_location_details(loc: Location) -> dict:
    bits = [loc.name]
    if loc.abbreviation:
        bits.append(loc.abbreviation)
    if loc.phone:
        bits.append(loc.phone)
    addr = " ".join(part for part in (loc.address, loc.city) if part)
    if addr:
        bits.append(addr)
    if loc.location_type:
        bits.append(loc.location_type)
    return {"ok": True, "topic": "location", "answer": " · ".join(bits) + "."}


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
                f"No patients are on the board at {label} {window['label']}.",
                topic="clinic",
                count=0,
            )
        return _talk(
            f"{label} {window['label']}: {patients} patient"
            f"{'' if patients == 1 else 's'} to be seen.",
            topic="clinic",
            count=patients,
        )
    if topic == "cases":
        n = len(cases)
        return {
            "ok": True,
            "topic": "cases",
            "answer": f"{label} had {n} surgical case{'s' if n != 1 else ''} {window['label']}.",
            "count": n,
        }
    return {
        "ok": True,
        "topic": "briefing",
        "answer": (
            f"{label} {window['label']}: {patients} clinic patients; "
            f"{len(cases)} surgical cases."
        ),
    }


def _answer_roster(db: Session) -> dict:
    rows = (
        db.query(Surgeon)
        .filter(Surgeon.is_active.is_(True))
        .order_by(Surgeon.last_name, Surgeon.first_name)
        .all()
    )
    names = [row.full_name for row in rows if surgeon_is_visible(row)]
    if not names:
        return {"ok": True, "topic": "roster", "answer": "No active surgeons on file."}
    return {
        "ok": True,
        "topic": "roster",
        "answer": f"{len(names)} surgeons: " + "; ".join(names[:40]) + ".",
        "count": len(names),
    }


def _answer_groups(db: Session) -> dict:
    call_groups = [row.name for row in db.query(CallGroup).order_by(CallGroup.sort_order).all() if row.name]
    clinic_groups = [
        row.name
        for row in db.query(ClinicGroup).filter(ClinicGroup.is_active.is_(True)).all()
        if row.name
    ]
    bits = []
    if call_groups:
        bits.append("Call groups: " + ", ".join(call_groups[:20]))
    if clinic_groups:
        bits.append("Clinic groups: " + ", ".join(clinic_groups[:20]))
    if not bits:
        return {"ok": True, "topic": "groups", "answer": "No call or clinic groups on file."}
    return {"ok": True, "topic": "groups", "answer": ". ".join(bits) + "."}


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
        return {
            "ok": True,
            "topic": "notices",
            "answer": "Admin Notifications: none unread.",
            "count": 0,
        }
    return {
        "ok": True,
        "topic": "notices",
        "answer": f"Admin Notifications ({len(titles)}): "
        + "; ".join(titles[:12])
        + ".",
        "count": len(titles),
    }


