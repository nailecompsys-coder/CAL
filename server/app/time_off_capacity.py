"""Time-off groups: yellow/red alerts when too many people would be off at once.

Chris's rule (surgeon in charge): if two docs already have time off, a third
overlapping request is yellow; if three are off, the next one is red and is not
sent. The doctors talk first, then Shannon can enter it.

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

    @property
    def half_day_label(self) -> str:
        return f"{self.day.strftime('%a %b %-d')} {self.session.upper()}"


@dataclass
class CapacityResult:
    hits: list[CapacityHit]
    initials: dict[int, str]

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
        hit = self.worst_hit()
        if not hit:
            return ""
        who = self.names(hit)
        if hit.level == "red":
            return (
                f"Not sent: {hit.off_count} would be off {hit.half_day_label}{self._more(hit)} "
                f"({hit.group_name}). Please talk with {who or 'the other doctors'} first. "
                f"Shannon can enter it once you agree."
            )
        return (
            f"Heads up: {who or 'others'} {'is' if len(hit.other_ids) == 1 else 'are'} already off "
            f"{hit.half_day_label}{self._more(hit)} ({hit.group_name}: {hit.off_count} would be off). "
            f"Your request was sent to Shannon."
        )

    def admin_message(self) -> str:
        hit = self.worst_hit()
        if not hit:
            return ""
        who = self.names(hit)
        limit = hit.red_at if hit.level == "red" else hit.yellow_at
        return (
            f"{'RED' if hit.level == 'red' else 'Yellow'}: {hit.off_count} off {hit.half_day_label}"
            f"{self._more(hit)} in {hit.group_name} ({hit.level} at {limit})"
            f"{'; also off: ' + who if who else ''}."
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
            hit.other_ids.append(int(row["other_surgeon_id"]))
    other_ids = {sid for hit in hits.values() for sid in hit.other_ids}
    initials = {
        s.id: s.initials
        for s in (db.query(Surgeon).filter(Surgeon.id.in_(other_ids)).all() if other_ids else [])
    }
    return CapacityResult(hits=list(hits.values()), initials=initials)


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
) -> None:
    """A red request was not sent: tell the admins (Shannon) on the dashboard and by text."""
    from .push import notify_admins

    span = start_date.strftime("%b %-d")
    if end_date != start_date:
        span += f" to {end_date.strftime('%b %-d')}"
    notify_admins(
        "Red alert: time off",
        f"{surgeon.full_name} asked for {span} and was stopped. {result.admin_message()}",
        db,
        kind="time_off_red",
        payload={
            "surgeonId": surgeon.id,
            "startDate": start_date.isoformat(),
            "endDate": end_date.isoformat(),
            "level": "red",
        },
        require_dayoff_opt_in=True,
        urgent_sms=True,
    )


def capacity_findings(result: CapacityResult) -> list:
    from .scheduling_guardrails_service import DayOffFinding

    findings = []
    seen = set()
    for hit in sorted(result.hits, key=lambda h: (h.day, h.session, -LEVEL_RANK[h.level], h.group_name)):
        key = (hit.group_id, hit.day, hit.session)
        if key in seen:
            continue
        seen.add(key)
        single = CapacityResult(hits=[hit], initials=result.initials)
        findings.append(DayOffFinding(
            severity=hit.level,
            kind="time_off_capacity",
            date=hit.day,
            message=single.admin_message(),
            # One summary for the surgeon, the same on every finding so it shows once.
            surgeon_message=result.surgeon_message(),
            clinic_group_id=hit.group_id,
            clinic_group_name=hit.group_name,
            approved_initials=sorted({result.initials.get(sid, "?") for sid in hit.other_ids}),
        ))
    return findings
