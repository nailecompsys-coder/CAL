"""Ask Grok-BOT anything the live CAL database can answer.

Answers come from CAL (and Aprima cache in this DB). No xAI call — PHI stays here.
If the question names a doctor and a window, Grok reads every schedule table for them.
Secrets, OTP codes, magic links, and device tokens are never in the answer.
"""
from __future__ import annotations

import calendar
import re
from datetime import date, timedelta

from sqlalchemy.orm import Session, joinedload

from .ingest_resolve import resolve_surgeon
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
from .practice_time import practice_now, practice_today
from .surgeon_visibility import surgeon_is_visible

_MONTHS = {name.lower(): i for i, name in enumerate(calendar.month_name) if name}
_MONTHS.update({name.lower(): i for i, name in enumerate(calendar.month_abbr) if name})

_NOISE = re.compile(
    r"\b(how|many|much|days?|has|have|had|did|does|do|take|taken|took|off|"
    r"last|this|previous|next|month|week|year|in|at|the|a|an|and|of|to|for|"
    r"about|please|what|when|where|who|which|is|was|were|are|be|been|"
    r"grok|bot|schedule|schedules|clinic|clinics|clinical|clinically|"
    r"patient|patients|see|saw|seen|"
    r"case|cases|surgery|surgeries|surgical|call|cover|covering|on|"
    r"meeting|meetings|block|blocks|room|rooms|count|number|total|"
    r"yesterday|today|tomorrow|approved|pending|list|tell|me|show|"
    r"phone|email|address|working|work|date|dates|mtd|ytd|through|thru|"
    r"far|currently|upto|until|question|scheduled|schedule|"
    r"coverage|covering|cover)\b",
    re.IGNORECASE,
)

_DATE_TOKEN = re.compile(r"\b(\d{1,2})[/\-](\d{1,2})(?:[/\-](\d{2,4}))?\b")
_ISO_DATE = re.compile(r"\b(20\d{2})-(\d{2})-(\d{2})\b")
_SECRET_KINDS = frozenset({
    "otp", "magic_link", "device", "password", "token", "secret",
})


def ask_grok(
    db: Session,
    question: str,
    *,
    today: date | None = None,
    admin_user_id: int | None = None,
) -> dict:
    today = today or practice_today()
    raw = " ".join((question or "").split())
    if not raw:
        return {
            "ok": False,
            "answer": (
                "Ask me anything — what today or tomorrow is, who is off, "
                "clinic patients, cases, call, meetings, or a location."
            ),
        }

    window = parse_window(raw, today)
    topic = parse_topic(raw)
    if topic == "when":
        return _answer_when(raw, today)
    if topic == "identity":
        return _answer_identity()
    surgeon = _surgeon_from_question(db, raw)
    if isinstance(surgeon, dict):
        return surgeon
    location = _location_from_question(db, raw)
    patient_hit = _patient_from_question(db, raw) if not surgeon else None

    if topic == "roster":
        return _answer_roster(db)
    if topic == "notices":
        return _answer_notices(db, admin_user_id)
    if topic == "groups":
        return _answer_groups(db)
    if topic == "who_off":
        return _answer_who_off(db, window)
    if topic == "who_call":
        return _answer_who_call(db, window)
    if topic == "who_clinic":
        return _answer_who_clinic(db, window)
    if topic == "pending_off":
        return _answer_pending_off(db, window)
    if topic == "meetings":
        if surgeon:
            facts = collect_surgeon_facts(db, surgeon, window["start"], window["end"])
            return _answer_meetings(surgeon, window, facts)
        return _answer_meetings_board(db, window)
    if topic == "cases" and not surgeon:
        return _answer_cases_board(db, window)
    if topic == "time_off" and not surgeon:
        return _answer_who_off(db, window)
    if topic == "clinic" and not surgeon:
        return _answer_who_clinic(db, window)
    if topic == "call" and not surgeon:
        return _answer_who_call(db, window)
    if topic == "blocks" and not surgeon:
        return _answer_blocks_board(db, window)
    if topic == "board":
        return _answer_board(db, window)
    if topic == "location" and not location:
        return _answer_locations_board(db)
    if topic == "location" and location:
        return _answer_location_details(location)
    if topic == "contact" and surgeon:
        return _answer_contact(surgeon)
    if patient_hit and topic in {"patient", "unknown", "briefing"}:
        return patient_hit
    if surgeon:
        facts = collect_surgeon_facts(db, surgeon, window["start"], window["end"])
        if topic == "time_off":
            return _answer_time_off(surgeon, window, facts)
        if topic == "clinic":
            return _answer_clinic(surgeon, window, facts)
        if topic == "cases":
            return _answer_cases(surgeon, window, facts)
        if topic == "call":
            return _answer_call(surgeon, window, facts)
        if topic == "meetings":
            return _answer_meetings(surgeon, window, facts)
        if topic == "blocks":
            return _answer_blocks(surgeon, window, facts)
        if topic == "availability":
            return _answer_availability(surgeon, window, facts)
        if topic == "contact":
            return _answer_contact(surgeon)
        return _answer_briefing(surgeon, window, facts)

    if location and topic in {"clinic", "cases", "briefing", "unknown"}:
        return _answer_location_volume(db, location, window, topic)

    if topic in {"briefing", "unknown"} and _looks_like_live_ask(raw):
        return _answer_board(db, window)

    return _answer_freeform(raw, today)


def parse_window(text: str, today: date) -> dict:
    blob = text.lower()
    iso = _ISO_DATE.search(blob)
    if iso:
        day = date(int(iso.group(1)), int(iso.group(2)), int(iso.group(3)))
        return _window(day, day, day.strftime("%b %-d, %Y"))
    slash = _DATE_TOKEN.search(blob)
    if slash:
        mo, d = int(slash.group(1)), int(slash.group(2))
        year = int(slash.group(3)) if slash.group(3) else today.year
        if year < 100:
            year += 2000 if year < 50 else 1900
        try:
            day = date(year, mo, d)
            return _window(day, day, day.strftime("%b %-d, %Y"))
        except ValueError:
            pass
    if "yesterday" in blob:
        day = today - timedelta(days=1)
        return _window(day, day, "yesterday")
    if "tomorrow" in blob:
        day = today + timedelta(days=1)
        return _window(day, day, "tomorrow")
    if re.search(r"\btoday\b", blob):
        return _window(today, today, "today")
    if "last week" in blob or "previous week" in blob:
        mon = today - timedelta(days=today.weekday() + 7)
        return _window(mon, mon + timedelta(days=6), f"last week ({_span(mon, mon + timedelta(days=6))})")
    if "next week" in blob:
        mon = today - timedelta(days=today.weekday()) + timedelta(days=7)
        return _window(mon, mon + timedelta(days=6), f"next week ({_span(mon, mon + timedelta(days=6))})")
    if "this week" in blob:
        mon = today - timedelta(days=today.weekday())
        return _window(mon, mon + timedelta(days=6), f"this week ({_span(mon, mon + timedelta(days=6))})")
    if "last month" in blob or "previous month" in blob:
        first_this = today.replace(day=1)
        last_prev = first_this - timedelta(days=1)
        first_prev = last_prev.replace(day=1)
        return _window(first_prev, last_prev, last_prev.strftime("%B %Y"))
    if "this month" in blob and re.search(r"\b(to date|so far|mtd|year to date)\b", blob):
        first = today.replace(day=1)
        return _window(first, today, f"{today.strftime('%B %Y')} to date")
    if "this month" in blob:
        first = today.replace(day=1)
        last_day = calendar.monthrange(today.year, today.month)[1]
        return _window(first, today.replace(day=last_day), today.strftime("%B %Y"))
    if "next month" in blob:
        first_next = (today.replace(day=28) + timedelta(days=8)).replace(day=1)
        last_day = calendar.monthrange(first_next.year, first_next.month)[1]
        last_next = first_next.replace(day=last_day)
        return _window(first_next, last_next, first_next.strftime("%B %Y"))
    for name, month in _MONTHS.items():
        if re.search(rf"\b{re.escape(name)}\b", blob):
            year = today.year
            ymatch = re.search(r"\b(20\d{2})\b", blob)
            if ymatch:
                year = int(ymatch.group(1))
            elif month > today.month + 1:
                year -= 1
            last_day = calendar.monthrange(year, month)[1]
            start = date(year, month, 1)
            end = date(year, month, last_day)
            return _window(start, end, start.strftime("%B %Y"))
    mon = today - timedelta(days=today.weekday())
    return _window(mon, mon + timedelta(days=6), f"this week ({_span(mon, mon + timedelta(days=6))})")


_CALL_WORDS = (
    r"(?:on[- ]call|call schedule|covering call|coverage|covering|"
    r"\bcover\b|\bcall\b)"
)


def parse_topic(text: str) -> str:
    """Map practice English onto a live-board topic.

    Add a synonym here and a line in tests.QUESTION_CATALOG when Ask misses.
    """
    blob = text.lower()
    if _is_when_question(blob):
        return "when"
    if _is_identity_question(blob):
        return "identity"
    if re.search(r"\bwho\b", blob) and re.search(r"\b(off|time off)\b", blob):
        return "who_off"
    if re.search(r"\bwho\b", blob) and re.search(_CALL_WORDS, blob):
        return "who_call"
    if re.search(r"\bwho\b", blob) and re.search(r"\bclinic\b", blob):
        return "who_clinic"
    if re.search(r"\bpending\b", blob) and re.search(r"\boff\b", blob):
        return "pending_off"
    if re.search(r"\b(list|who are|all the)\b", blob) and re.search(
        r"\b(surgeons?|doctors?|physicians?)\b", blob
    ):
        return "roster"
    if re.search(r"\b(notices?|notifications?|leftover card)\b", blob):
        return "notices"
    if re.search(r"\b(clinic groups?|call groups?)\b", blob):
        return "groups"
    if re.search(r"\b(phone|email|contact)\b", blob) and not re.search(r"\b(where is)\b", blob):
        return "contact"
    if re.search(r"\b(patient|patients|clinic visit|clinical|saw|seen)\b", blob) and not re.search(
        r"\b(time off|day off|days off)\b", blob
    ):
        return "clinic"
    if re.search(
        r"\b(time off|day off|days off|vacation|taken off|took off|request(?:ed)? off)\b",
        blob,
    ):
        return "time_off"
    if re.search(r"\b(case|cases|surgery|surgeries|or case)\b", blob):
        return "cases"
    if re.search(_CALL_WORDS, blob):
        return "call"
    if re.search(r"\b(meetings?|huddle|tumor board)\b", blob):
        return "meetings"
    if re.search(r"\b(block or|or block|blocks?)\b", blob):
        return "blocks"
    if re.search(r"\b(available|availability|personal item)\b", blob):
        return "availability"
    if re.search(r"\b(locations?|facilities|where do we (work|operate))\b", blob):
        return "location"
    if re.search(
        r"\b(what(?:'?s| is) scheduled|on the (board|calendar|schedule)|"
        r"who(?:'?s| is) working)\b",
        blob,
    ):
        return "board"
    if re.search(r"\b(phone|address|where is)\b", blob):
        return "location"
    return "briefing"


def _looks_like_live_ask(text: str) -> bool:
    blob = text.lower()
    if not re.search(r"\b(who|what|which|list|show|any|scheduled|schedule)\b", blob):
        return False
    return bool(
        re.search(
            r"\b(today|tomorrow|yesterday|tonight|this week|next week|"
            r"this month|next month|this year)\b",
            blob,
        )
    )


def _is_when_question(blob: str) -> bool:
    if re.search(r"\bwho\b", blob):
        return False
    if re.search(
        r"\b(time off|day off|days off|clinic|patient|case|surgery|call|meeting|block|"
        r"board|calendar|schedule|coverage|covering|working)\b",
        blob,
    ):
        return False
    if re.search(r"\bwhat time\b", blob):
        return True
    if re.search(r"\b(what(?:'?s| is)|what day|what date)\b", blob) and re.search(
        r"\b(today|tomorrow|yesterday|date|day|it)\b", blob
    ):
        return True
    stripped = re.sub(r"[^a-z\s]", " ", blob)
    stripped = " ".join(stripped.split())
    return stripped in {
        "today",
        "tomorrow",
        "yesterday",
        "the date",
        "what day",
        "what date",
        "whats today",
        "whats tomorrow",
        "whats yesterday",
    }


def _is_identity_question(blob: str) -> bool:
    stripped = re.sub(r"[^a-z\s]", " ", blob)
    stripped = " ".join(stripped.split())
    if stripped in {"help", "help me"}:
        return True
    return bool(
        re.search(
            r"\b(who are you|what are you|what can you do|what do you do)\b",
            blob,
        )
    )


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
            "I'm Grok-BOT. Ask me anything — what today or tomorrow is, "
            "who is off, clinic patients, cases, call, meetings, or a location. "
            "I stay inside CAL. Nothing leaves the app."
        ),
    }


def _answer_freeform(text: str, today: date) -> dict:
    blob = text.lower()
    if _is_when_question(blob) or (
        re.search(r"\b(today|tomorrow|yesterday)\b", blob)
        and not re.search(r"\bwho\b", blob)
        and len(blob.split()) <= 8
    ):
        return _answer_when(text, today)
    if _is_identity_question(blob):
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
            "Ask me meetings, who is off, clinic patients, cases, call, or a doctor by name."
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


def _surgeon_from_question(db: Session, question: str):
    cleaned = _NOISE.sub(" ", question)
    cleaned = re.sub(r"[^A-Za-z\s'\-]", " ", cleaned)
    cleaned = " ".join(cleaned.split())
    if cleaned:
        hit = resolve_surgeon(db, cleaned)
        if hit:
            return hit
    tokens = [
        tok
        for tok in re.findall(r"[A-Za-z][A-Za-z'\-]{1,}", cleaned or question or "")
        if tok.lower() not in {"so", "far"}
    ]
    if tokens:
        hit = resolve_surgeon(db, " ".join(tokens))
        if hit:
            return hit
    surgeons = [
        row
        for row in db.query(Surgeon).filter(Surgeon.is_active.is_(True)).all()
        if surgeon_is_visible(row)
    ]
    first_hits: list[Surgeon] = []
    last_hits: list[Surgeon] = []
    initial_hits: list[Surgeon] = []
    prefix_hits: list[Surgeon] = []
    for tok in tokens:
        key = tok.lower()
        for row in surgeons:
            first = (row.first_name or "").split()[0].lower() if row.first_name else ""
            last = (row.last_name or "").split()[-1].lower() if row.last_name else ""
            initials = (row.initials or "").lower()
            if first == key and row not in first_hits:
                first_hits.append(row)
            elif first.startswith(key) and len(key) >= 4 and row not in prefix_hits:
                prefix_hits.append(row)
            if last == key and row not in last_hits:
                last_hits.append(row)
            if len(key) <= 3 and initials == key and row not in initial_hits:
                initial_hits.append(row)
    for group in (last_hits, first_hits, prefix_hits, initial_hits):
        if len(group) == 1:
            return group[0]
        if len(group) > 1:
            names = "; ".join(row.full_name for row in group[:8])
            return {
                "ok": True,
                "topic": "ambiguous",
                "answer": f"Which one: {names}?",
            }
    return None


def _location_from_question(db: Session, question: str) -> Location | None:
    blob = (question or "").lower()
    if not blob:
        return None
    rows = db.query(Location).filter(Location.is_active.is_(True)).all()
    hits: list[tuple[int, Location]] = []
    for loc in rows:
        name = (loc.name or "").strip().lower()
        abbr = (loc.abbreviation or "").strip().lower()
        if name and name in blob:
            hits.append((len(name), loc))
            continue
        if abbr and len(abbr) >= 3 and re.search(rf"\b{re.escape(abbr)}\b", blob, re.IGNORECASE):
            hits.append((len(abbr), loc))
    if not hits:
        return None
    hits.sort(key=lambda row: row[0], reverse=True)
    return hits[0][1]


def _patient_from_question(db: Session, question: str) -> dict | None:
    cleaned = _NOISE.sub(" ", question)
    cleaned = " ".join(re.sub(r"[^A-Za-z\s'\-,]", " ", cleaned).split())
    if len(cleaned) < 3:
        return None
    needle = cleaned.lower()
    rows = (
        db.query(SurgicalCase)
        .options(joinedload(SurgicalCase.surgeon), joinedload(SurgicalCase.location))
        .filter(SurgicalCase.status != "cancelled")
        .order_by(SurgicalCase.date.desc())
        .limit(400)
        .all()
    )
    hits = []
    for row in rows:
        name = (row.patient_name or "").lower()
        last = name.split(",")[0].strip()
        if needle in name or (last and last in needle):
            hits.append(row)
    if not hits:
        return None
    row = hits[0]
    clock = row.start_time.strftime("%H:%M") if row.start_time else "no start time yet"
    who = row.surgeon.full_name if row.surgeon else "unassigned"
    loc = ""
    if row.location:
        loc = f" at {row.location.abbreviation or row.location.name}"
    return {
        "ok": True,
        "topic": "patient",
        "answer": (
            f"{row.patient_name} is on {who}'s board {row.date.strftime('%b %-d, %Y')} "
            f"at {clock}{loc}"
            + (f" · {row.procedure}" if row.procedure else "")
            + "."
        ),
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
        f"{len(rows)} meeting{'' if len(rows) == 1 else 's'} {window['label']}:"
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
    heading = f"{len(rows)} surgical case{'' if len(rows) == 1 else 's'} {window['label']}:"
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
    rows = (
        db.query(DayOff)
        .options(joinedload(DayOff.surgeon))
        .filter(
            DayOff.status.in_(("approved", "pending")),
            DayOff.start_date <= window["end"],
            DayOff.end_date >= window["start"],
        )
        .all()
    )
    names = []
    for row in rows:
        if not surgeon_is_visible(row.surgeon):
            continue
        label = f"{row.surgeon.full_name} ({row.status})"
        if label not in names:
            names.append(label)
    if not names:
        return {"ok": True, "topic": "who_off", "answer": f"Nobody is off {window['label']}."}
    return {
        "ok": True,
        "topic": "who_off",
        "answer": f"Off {window['label']}: " + "; ".join(names[:20]) + ".",
        "count": len(names),
    }


def _answer_pending_off(db: Session, window: dict) -> dict:
    rows = (
        db.query(DayOff)
        .options(joinedload(DayOff.surgeon))
        .filter(
            DayOff.status == "pending",
            DayOff.start_date <= window["end"],
            DayOff.end_date >= window["start"],
        )
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
        return {
            "ok": True,
            "topic": "pending_off",
            "answer": f"No pending time-off requests {window['label']}.",
            "count": 0,
        }
    return {
        "ok": True,
        "topic": "pending_off",
        "answer": f"Pending time off {window['label']}: " + "; ".join(names[:20]) + ".",
        "count": len(names),
    }


def _answer_who_call(db: Session, window: dict) -> dict:
    rows = (
        db.query(CallRotation)
        .options(
            joinedload(CallRotation.surgeon),
            joinedload(CallRotation.call_group),
            joinedload(CallRotation.coverages).joinedload(CallCoverage.covering_surgeon),
        )
        .filter(CallRotation.date >= window["start"], CallRotation.date <= window["end"])
        .all()
    )
    bits = []
    for row in rows:
        group = row.call_group.name if row.call_group else "call"
        active = row.active_coverage
        if active:
            covering = active.covering_surgeon or db.get(Surgeon, active.covering_surgeon_id)
            if covering and surgeon_is_visible(covering):
                bits.append(f"{covering.full_name} covering {group} {row.date.strftime('%b %-d')}")
            continue
        if row.surgeon and surgeon_is_visible(row.surgeon):
            bits.append(f"{row.surgeon.full_name} on {group} {row.date.strftime('%b %-d')}")
    if not bits:
        return {"ok": True, "topic": "who_call", "answer": f"No call assignments {window['label']}."}
    return {
        "ok": True,
        "topic": "who_call",
        "answer": "; ".join(bits[:20]) + ".",
        "count": len(bits),
    }


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
    label = loc.abbreviation or loc.name
    if topic == "clinic":
        return {
            "ok": True,
            "topic": "clinic",
            "answer": f"{label} had {patients} clinic patients {window['label']}.",
            "count": patients,
        }
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
            "answer": "No open notices on the board.",
            "count": 0,
        }
    return {
        "ok": True,
        "topic": "notices",
        "answer": f"{len(titles)} open notice{'s' if len(titles) != 1 else ''}: "
        + "; ".join(titles[:12])
        + ".",
        "count": len(titles),
    }


def _window(start: date, end: date, label: str) -> dict:
    return {"start": start, "end": end, "label": label}


def _span(start: date, end: date) -> str:
    if start == end:
        return start.strftime("%b %-d")
    if start.month == end.month:
        return f"{start.strftime('%b %-d')}–{end.strftime('%-d')}"
    return f"{start.strftime('%b %-d')}–{end.strftime('%b %-d')}"
