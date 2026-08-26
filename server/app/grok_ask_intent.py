"""Turn an Ask sentence into slots: when, where, who, what.

No LLM. Portal labels and live names in the DB are the vocabulary.
New miss: add a QUESTION_CATALOG line and a row in _UI_LABELS, not another
if-ladder in the dispatcher.
"""
from __future__ import annotations

import calendar
import re
from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy.orm import Session, joinedload

from .ingest_resolve import resolve_surgeon
from .models import Location, Surgeon, SurgicalCase
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
    r"coverage|covering|cover|visits?|available|approvals?|notifications?|"
    r"monday|tuesday|wednesday|thursday|friday|saturday|sunday|office)\b",
    re.IGNORECASE,
)

_DATE_TOKEN = re.compile(r"\b(\d{1,2})[/\-](\d{1,2})(?:[/\-](\d{2,4}))?\b")
_ISO_DATE = re.compile(r"\b(20\d{2})-(\d{2})-(\d{2})\b")

_WEEKDAYS = {
    "monday": 0,
    "tuesday": 1,
    "wednesday": 2,
    "thursday": 3,
    "friday": 4,
    "saturday": 5,
    "sunday": 6,
    "mon": 0,
    "tue": 1,
    "tues": 1,
    "wed": 2,
    "thu": 3,
    "thur": 3,
    "thurs": 3,
    "fri": 4,
    "sat": 5,
    "sun": 6,
}
_GENERIC_LOC_WORDS = frozenset({
    "office", "clinic", "hospital", "center", "surgery", "surgical",
    "one", "main", "or", "the", "and",
})

_CALL_WORDS = (
    r"(?:on[- ]call|call schedule|covering call|coverage|covering|"
    r"\bcover\b|\bcall\b)"
)

# Portal labels → the same live query the screen already runs.
# Longest / most specific first. Add a catalog test when a label misses.
_UI_LABELS = (
    (r"today'?s coverage", "who_call"),
    (r"no on-call coverage", "who_call"),
    (r"surgical cases", "cases"),
    (r"clinic visits", "clinic_visits"),
    (r"clinics?\s*/\s*or", "clinics_or"),
    (r"no call(?: today)?", "no_call"),
    (r"available today", "available"),
    (r"pending approvals?", "pending_off"),
    (r"pending approval", "pending_off"),
    (r"meetings this week", "meetings"),
    (r"upcoming meetings", "meetings"),
    (r"admin notifications?", "notices"),
    (r"scheduling flags", "notices"),
    (r"desk ingest", "notices"),
    (r"out today", "who_off"),
    (r"who'?s out", "who_off"),
    (r"master calendar", "board"),
    (r"block or", "blocks"),
    (r"open block or", "blocks"),
    (r"assigned block or", "blocks"),
    (r"call schedule", "who_call"),
    (r"time off", "time_off"),
    (r"days off", "time_off"),
    (r"call groups?", "groups"),
    (r"clinic groups?", "groups"),
    (r"physicians", "roster"),
    (r"clinics?\s*/\s*offices?", "location"),
    (r"hospitals?\s*/\s*surgery centers?", "location"),
)

# Named office + clinic/patients must beat the board-wide clinic roster.
LOCATION_CLINIC_TOPICS = frozenset({"clinic", "clinic_visits", "who_clinic", "clinics_or"})
LOCATION_VOLUME_TOPICS = frozenset({"clinic", "cases", "briefing", "unknown"})


@dataclass(slots=True)
class AskIntent:
    question: str
    today: date
    window: dict
    topic: str
    surgeon: Surgeon | None = None
    location: Location | None = None
    patient: dict | None = None


def parse_intent(db: Session, question: str, today: date) -> AskIntent | dict:
    """Fill slots from the question. Ambiguous surgeon names return a talk dict."""
    window = parse_window(question, today)
    topic = parse_topic(question)
    if topic in {"when", "identity"}:
        return AskIntent(question=question, today=today, window=window, topic=topic)
    surgeon = surgeon_from_question(db, question)
    if isinstance(surgeon, dict):
        return surgeon
    location = location_from_question(db, question)
    patient = patient_from_question(db, question) if not surgeon else None
    return AskIntent(
        question=question,
        today=today,
        window=window,
        topic=topic,
        surgeon=surgeon,
        location=location,
        patient=patient,
    )


def parse_window(text: str, today: date) -> dict:
    blob = text.lower()
    iso = _ISO_DATE.search(blob)
    if iso:
        day = date(int(iso.group(1)), int(iso.group(2)), int(iso.group(3)))
        return window(day, day, day.strftime("%b %-d, %Y"))
    slash = _DATE_TOKEN.search(blob)
    if slash:
        mo, d = int(slash.group(1)), int(slash.group(2))
        year = int(slash.group(3)) if slash.group(3) else today.year
        if year < 100:
            year += 2000 if year < 50 else 1900
        try:
            day = date(year, mo, d)
            return window(day, day, day.strftime("%b %-d, %Y"))
        except ValueError:
            pass
    if "yesterday" in blob:
        day = today - timedelta(days=1)
        return window(day, day, "yesterday")
    if "tomorrow" in blob:
        day = today + timedelta(days=1)
        return window(day, day, "tomorrow")
    if re.search(r"\btoday\b", blob):
        return window(today, today, "today")
    weekday = _weekday_window(blob, today)
    if weekday:
        return weekday
    if re.search(r"\b(upcoming meetings|meetings this week)\b", blob):
        return window(today, today + timedelta(days=7), "this week")
    if "last week" in blob or "previous week" in blob:
        mon = today - timedelta(days=today.weekday() + 7)
        return window(mon, mon + timedelta(days=6), f"last week ({span(mon, mon + timedelta(days=6))})")
    if "next week" in blob:
        mon = today - timedelta(days=today.weekday()) + timedelta(days=7)
        return window(mon, mon + timedelta(days=6), f"next week ({span(mon, mon + timedelta(days=6))})")
    if "this week" in blob:
        mon = today - timedelta(days=today.weekday())
        return window(mon, mon + timedelta(days=6), f"this week ({span(mon, mon + timedelta(days=6))})")
    if "last month" in blob or "previous month" in blob:
        first_this = today.replace(day=1)
        last_prev = first_this - timedelta(days=1)
        first_prev = last_prev.replace(day=1)
        return window(first_prev, last_prev, last_prev.strftime("%B %Y"))
    if "this month" in blob and re.search(r"\b(to date|so far|mtd|year to date)\b", blob):
        first = today.replace(day=1)
        return window(first, today, f"{today.strftime('%B %Y')} to date")
    if "this month" in blob:
        first = today.replace(day=1)
        last_day = calendar.monthrange(today.year, today.month)[1]
        return window(first, today.replace(day=last_day), today.strftime("%B %Y"))
    if "next month" in blob:
        first_next = (today.replace(day=28) + timedelta(days=8)).replace(day=1)
        last_day = calendar.monthrange(first_next.year, first_next.month)[1]
        last_next = first_next.replace(day=last_day)
        return window(first_next, last_next, first_next.strftime("%B %Y"))
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
            return window(start, end, start.strftime("%B %Y"))
    mon = today - timedelta(days=today.weekday())
    return window(mon, mon + timedelta(days=6), f"this week ({span(mon, mon + timedelta(days=6))})")


def parse_topic(text: str) -> str:
    """Map portal language onto the live query for that screen."""
    blob = text.lower()
    if is_when_question(blob):
        return "when"
    if is_identity_question(blob):
        return "identity"
    for pattern, topic in _UI_LABELS:
        if re.search(pattern, blob):
            return topic
    if re.search(r"\bno call\b", blob):
        return "no_call"
    if re.search(r"\bwho\b", blob) and re.search(r"\b(off|time off|out today)\b", blob):
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
    if re.search(r"\b(availability|personal item)\b", blob):
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


def looks_like_live_ask(text: str) -> bool:
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


def is_when_question(blob: str) -> bool:
    if re.search(r"\bwho\b", blob):
        return False
    if re.search(
        r"\b(time off|day off|days off|clinic|patient|case|surgery|call|meeting|block|"
        r"board|calendar|schedule|coverage|covering|working|visits?|available|"
        r"pending|notification|physician|dashboard)\b",
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


def is_identity_question(blob: str) -> bool:
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


def surgeon_from_question(db: Session, question: str):
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


def location_needles(loc: Location) -> list[str]:
    bits: list[str] = []
    for raw in (loc.name, loc.abbreviation, loc.city):
        text = (raw or "").strip().lower()
        if text:
            bits.append(text)
        for tok in re.findall(r"[a-z]{4,}", text):
            if tok not in _GENERIC_LOC_WORDS and tok not in bits:
                bits.append(tok)
    return bits


def location_from_question(db: Session, question: str) -> Location | None:
    blob = (question or "").lower()
    if not blob:
        return None
    rows = db.query(Location).filter(Location.is_active.is_(True)).all()
    hits: list[tuple[int, Location]] = []
    for loc in rows:
        name = (loc.name or "").strip().lower()
        abbr = (loc.abbreviation or "").strip().lower()
        if name and name in blob:
            hits.append((100 + len(name), loc))
            continue
        if abbr and len(abbr) >= 3 and re.search(rf"\b{re.escape(abbr)}\b", blob, re.IGNORECASE):
            hits.append((len(abbr), loc))
            continue
        for needle in location_needles(loc):
            if needle == name:
                continue
            if re.search(rf"\b{re.escape(needle)}\b", blob):
                hits.append((len(needle), loc))
                break
    if not hits:
        return None
    hits.sort(key=lambda row: row[0], reverse=True)
    return hits[0][1]


def patient_from_question(db: Session, question: str) -> dict | None:
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


def window(start: date, end: date, label: str) -> dict:
    return {"start": start, "end": end, "label": label}


def span(start: date, end: date) -> str:
    if start == end:
        return start.strftime("%b %-d")
    if start.month == end.month:
        return f"{start.strftime('%b %-d')}–{end.strftime('%-d')}"
    return f"{start.strftime('%b %-d')}–{end.strftime('%b %-d')}"


def _weekday_window(blob: str, today: date) -> dict | None:
    for name, wd in _WEEKDAYS.items():
        if not re.search(rf"\b{name}\b", blob):
            continue
        if re.search(rf"\b(last|previous) {name}\b", blob):
            delta = today.weekday() - wd
            if delta <= 0:
                delta += 7
            day = today - timedelta(days=delta)
        elif re.search(rf"\bnext {name}\b", blob):
            delta = wd - today.weekday()
            if delta <= 0:
                delta += 7
            day = today + timedelta(days=delta)
        else:
            day = today + timedelta(days=(wd - today.weekday()) % 7)
        return window(day, day, f"{name.title()} ({day.strftime('%b %-d')})")
    return None
