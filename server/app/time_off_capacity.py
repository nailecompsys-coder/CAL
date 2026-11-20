"""Time-off groups: yellow/red alerts when too many people would be off at once.

Chris's rule (surgeon in charge): two doctors off at the same time is yellow.
A third request is red: the surgeon sees who is already off (approved or
pending) and either cancels to pick other dates or sends it anyway, which
saves the request and gives Shannon a red alert to sort out.

SQL (sql/time_off_capacity.sql) does the counting per group and half-day.
This module picks the request's half-days, runs that SQL, and words the result.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date, time
from pathlib import Path

from sqlalchemy import bindparam, text
from sqlalchemy.orm import Session

from .day_off_card_normalization import _covers_session
from .models import DayOff, ScheduleCard, Surgeon
from .surgeon_visibility import surgeon_is_hidden

_SQL = text(
    Path(__file__).with_name("sql").joinpath("time_off_capacity.sql").read_text()
).bindparams(
    bindparam("card_ids", expanding=True),
    bindparam("hidden_ids", expanding=True),
)

LEVEL_RANK = {None: 0, "yellow": 1, "red": 2}


@dataclass
class CapacityHit:
    group_id: int
    group_name: str
    day: date
    session: str
    off_count: int
    level: str
    yellow_at: int | None
    red_at: int | None
    other_ids: list[int] = field(default_factory=list)
    other_status: dict[int, str] = field(default_factory=dict)

    @property
    def half_day_label(self) -> str:
        return f"{self.day.strftime('%a %b %-d')} {self.session.upper()}"


@dataclass
class CapacityResult:
    hits: list[CapacityHit]
    initials: dict[int, str]
    names_by_id: dict[int, str] = field(default_factory=dict)

    @property
    def level(self) -> str | None:
        best = None
        for hit in self.hits:
            if LEVEL_RANK[hit.level] > LEVEL_RANK[best]:
                best = hit.level
        return best

    @property
    def is_red(self) -> bool:
        return self.level == "red"

    def worst_hit(self) -> CapacityHit | None:
        if not self.hits:
            return None
        # Highest level first, then the busiest half-day, then the earliest.
        return sorted(
            self.hits,
            key=lambda h: (-LEVEL_RANK[h.level], -h.off_count, h.day, h.session),
        )[0]

    def names(self, hit: CapacityHit) -> str:
        labels = sorted({self.initials.get(sid, "?") for sid in hit.other_ids})
        if not labels:
            return ""
        if len(labels) == 1:
            return labels[0]
        return ", ".join(labels[:-1]) + " and " + labels[-1]

    def _more(self, hit: CapacityHit) -> str:
        others = {(h.day, h.session) for h in self.hits if h.level == hit.level} - {(hit.day, hit.session)}
        if not others:
            return ""
        return f" (and {len(others)} more half-day{'s' if len(others) != 1 else ''})"

    def surgeon_message(self) -> str:
        """Before the surgeon decides: what yellow or red means for this request."""
        hit = self.worst_hit()
        if not hit:
            return ""
        who = self.names(hit)
        if hit.level == "red":
            return (
                f"Red alert: you would make {hit.off_count} off {hit.half_day_label}{self._more(hit)}. "
                f"Already off: {who or 'others'}. Cancel and pick other dates, "
                f"or Send to Shannon and she will work it out."
            )
        return (
            f"Heads up: {who or 'others'} {'is' if len(hit.other_ids) == 1 else 'are'} already off "
            f"{hit.half_day_label}{self._more(hit)} ({hit.off_count} would be off). "
            f"Your request was sent to Shannon."
        )

    def red_days_label(self) -> str:
        """'Fri Dec 4 (3 off), Mon Dec 7 (3 off)' for the red days only."""
        return ", ".join(
            f"{line['label']} ({line['offCount']} off)"
            for line in self.day_lines() if line["level"] == "red"
        )

    def sent_red_message(self) -> str:
        """After the surgeon chose Send to Shannon."""
        if not self.is_red:
            return ""
        return f"Sent with a red alert for {self.red_days_label()}. Shannon will work it out with you."

    def day_lines(self) -> list[dict]:
        """Each requested day that is yellow or red, in date order (Chris: line them up).

        A day takes its worst half-day and group: the highest count and color, and
        everyone else off that day.
        """
        days: dict[date, dict] = {}
        for hit in self.hits:
            line = days.setdefault(hit.day, {"level": None, "offCount": 0, "ids": set()})
            if LEVEL_RANK[hit.level] > LEVEL_RANK[line["level"]]:
                line["level"] = hit.level
            line["offCount"] = max(line["offCount"], hit.off_count)
            line["ids"].update(hit.other_ids)
        out = []
        for day in sorted(days):
            line = days[day]
            out.append({
                "date": day.isoformat(),
                "label": day.strftime("%a %b %-d"),
                "level": line["level"],
                "offCount": line["offCount"],
                "others": sorted(self.initials.get(sid, "?") for sid in line["ids"]),
            })
        return out

    def off_list(self) -> list[dict]:
        """Who else is off during this request, for the phone's chip. No patient data."""
        people: dict[int, dict] = {}
        for hit in sorted(self.hits, key=lambda h: (h.day, h.session)):
            for sid in hit.other_ids:
                person = people.setdefault(sid, {
                    "surgeonId": sid,
                    "initials": self.initials.get(sid, "?"),
                    "name": self.names_by_id.get(sid, ""),
                    "status": "pending",
                    "when": [],
                })
                if hit.other_status.get(sid) == "approved":
                    person["status"] = "approved"
                label = hit.half_day_label
                if label not in person["when"]:
                    person["when"].append(label)
        out = []
        for person in people.values():
            out.append({**person, "when": _when_label(person["when"])})
        return sorted(out, key=lambda p: (p["status"] != "approved", p["initials"]))

    def admin_message(self) -> str:
        hit = self.worst_hit()
        if not hit:
            return ""
        if hit.level == "red" and len(self.hits) > 1:
            return f"RED: {self.red_days_label()} in {hit.group_name}."
        who = self.names(hit)
        limit = hit.red_at if hit.level == "red" else hit.yellow_at
        return (
            f"{'RED' if hit.level == 'red' else 'Yellow'}: {hit.off_count} off {hit.half_day_label}"
            f"{self._more(hit)} in {hit.group_name} ({hit.level} at {limit})"
            f"{'; also off: ' + who if who else ''}."
        )


def _when_label(half_days: list[str]) -> str:
    """'Fri Nov 27 AM' + 'Fri Nov 27 PM' reads as 'Fri Nov 27'."""
    by_day: dict[str, list[str]] = {}
    for label in half_days:
        day, session = label.rsplit(" ", 1)
        by_day.setdefault(day, []).append(session)
    return ", ".join(
        day if {"AM", "PM"} <= set(sessions) else f"{day} {sessions[0]}"
        for day, sessions in by_day.items()
    )


def _hidden_ids(db: Session) -> list[int]:
    ids = [s.id for s in db.query(Surgeon).all() if surgeon_is_hidden(s)]
    return ids or [-1]


def _candidate_card_ids(db: Session, request: DayOff) -> list[int]:
    if (request.reason or "").strip().lower() == "no call":
        return []
    cards = db.query(ScheduleCard).filter(
        ScheduleCard.surgeon_id == request.surgeon_id,
        ScheduleCard.date >= request.start_date,
        ScheduleCard.date <= request.end_date,
    ).all()
    return [card.id for card in cards if _covers_session(request, card.date, card.session)]


def _run(db: Session, request: DayOff, exclude_id: int | None) -> CapacityResult:
    card_ids = _candidate_card_ids(db, request)
    if not card_ids:
        return CapacityResult(hits=[], initials={})
    rows = db.execute(_SQL, {
        "surgeon_id": request.surgeon_id,
        "card_ids": card_ids,
        "exclude_id": exclude_id if exclude_id is not None else -1,
        "hidden_ids": _hidden_ids(db),
    }).mappings().all()
    hits: dict[tuple, CapacityHit] = {}
    for row in rows:
        day = row["day"] if isinstance(row["day"], date) else date.fromisoformat(str(row["day"])[:10])
        key = (row["group_id"], day, row["session"])
        hit = hits.get(key)
        if hit is None:
            hit = hits[key] = CapacityHit(
                group_id=row["group_id"],
                group_name=row["group_name"],
                day=day,
                session=row["session"],
                off_count=int(row["off_count"]),
                level=row["level"],
                yellow_at=row["yellow_at_off"],
                red_at=row["red_at_off"],
            )
        if row["other_surgeon_id"] is not None:
            sid = int(row["other_surgeon_id"])
            hit.other_ids.append(sid)
            hit.other_status[sid] = row["other_status"]
    other_ids = {sid for hit in hits.values() for sid in hit.other_ids}
    others = db.query(Surgeon).filter(Surgeon.id.in_(other_ids)).all() if other_ids else []
    return CapacityResult(
        hits=list(hits.values()),
        initials={s.id: s.initials for s in others},
        names_by_id={s.id: s.full_name for s in others},
    )


def check_new_request(
    db: Session,
    surgeon_id: int,
    *,
    start_date: date,
    end_date: date,
    reason: str = "",
    is_full_day: bool | None = None,
    start_time: time | None = None,
    end_time: time | None = None,
    segments: list[dict] | None = None,
    exclude_id: int | None = None,
) -> CapacityResult:
    """Count a request that is not saved yet (or an edit of request exclude_id)."""
    request = DayOff(
        surgeon_id=surgeon_id,
        start_date=start_date,
        end_date=end_date,
        reason=reason or "",
        is_full_day=True if is_full_day is None else is_full_day,
        start_time=start_time,
        end_time=end_time,
        segments=json.dumps(segments) if segments else None,
    )
    try:
        return _run(db, request, exclude_id)
    finally:
        # Never let the transient request ride into the session.
        if request in db:
            db.expunge(request)


def check_day_off(db: Session, dayoff: DayOff) -> CapacityResult:
    """Count a saved request against everyone else (Shannon's review)."""
    return _run(db, dayoff, dayoff.id)


def alert_red_request(
    db: Session,
    surgeon: Surgeon,
    result: CapacityResult,
    start_date: date,
    end_date: date,
    dayoff_id: int | None = None,
) -> None:
    """The surgeon sent a red request anyway: Shannon gets a red alert and a text."""
    from .push import notify_admins

    span = start_date.strftime("%b %-d")
    if end_date != start_date:
        span += f" to {end_date.strftime('%b %-d')}"
    already = ", ".join(
        f"{p['initials']} ({p['status']})" for p in result.off_list()
    )
    notify_admins(
        "Red alert: time off",
        f"{surgeon.full_name} sent a request for {span} anyway. {result.admin_message()}"
        + (f" Already off: {already}." if already else ""),
        db,
        kind="time_off_red",
        payload={
            "dayOffId": dayoff_id,
            "surgeonId": surgeon.id,
            "startDate": start_date.isoformat(),
            "endDate": end_date.isoformat(),
            "level": "red",
        },
        require_dayoff_opt_in=True,
        urgent_sms=True,
    )


def capacity_findings(result: CapacityResult) -> list:
    """One review finding per day for Shannon, red days first."""
    from .scheduling_guardrails_service import DayOffFinding

    by_day: dict[date, list[CapacityHit]] = {}
    for hit in result.hits:
        by_day.setdefault(hit.day, []).append(hit)
    findings = []
    for day, hits in by_day.items():
        worst = sorted(hits, key=lambda h: (-LEVEL_RANK[h.level], -h.off_count, h.group_name))[0]
        others = sorted({result.initials.get(sid, "?") for h in hits for sid in h.other_ids})
        findings.append(DayOffFinding(
            severity=worst.level,
            kind="time_off_capacity",
            date=day,
            message=(
                f"{'RED' if worst.level == 'red' else 'Yellow'}: {day.strftime('%a %b %-d')} · "
                f"{worst.off_count} off in {worst.group_name}"
                + (f"; also off: {', '.join(others)}" if others else "") + "."
            ),
            # One summary for the surgeon, the same on every finding so it shows once.
            surgeon_message=result.surgeon_message(),
            clinic_group_id=worst.group_id,
            clinic_group_name=worst.group_name,
            approved_initials=others,
        ))
    findings.sort(key=lambda f: (-LEVEL_RANK[f.severity], f.date))
    return findings
