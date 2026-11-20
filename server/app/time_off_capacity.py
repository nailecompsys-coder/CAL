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

_BOOKED_SQL = text(
    Path(__file__).with_name("sql").joinpath("time_off_booked.sql").read_text()
).bindparams(bindparam("card_ids", expanding=True))


def _booked_label(cases: int, visits: int) -> str:
    parts = []
    if cases:
        parts.append(f"{cases} case{'s' if cases != 1 else ''}")
    if visits:
        parts.append(f"{visits} visit{'s' if visits != 1 else ''}")
    return " and ".join(parts) + " booked"


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
    # Don (Nov 20): clinic visits or OR cases already booked on the requested
    # half-days make the request red. [{day, session, cases, visits}]
    booked: list[dict] = field(default_factory=list)

    @property
    def level(self) -> str | None:
        best = "red" if self.booked else None
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

    def booked_summary(self) -> str:
        """'Fri Dec 4 (3 cases booked), Mon Dec 7 AM (12 visits booked)'."""
        by_day: dict[date, dict] = {}
        for b in self.booked:
            entry = by_day.setdefault(b["day"], {"sessions": set(), "cases": 0, "visits": 0})
            entry["sessions"].add(b["session"])
            entry["cases"] += b["cases"]
            entry["visits"] += b["visits"]
        parts = []
        for day in sorted(by_day):
            e = by_day[day]
            when = day.strftime("%a %b %-d") + ("" if e["sessions"] == {"am", "pm"} else " " + next(iter(e["sessions"])).upper())
            parts.append(f"{when} ({_booked_label(e['cases'], e['visits'])})")
        return ", ".join(parts)

    def surgeon_message(self) -> str:
        """Before the surgeon decides: what yellow or red means for this request."""
        hit = self.worst_hit()
        if self.booked:
            text_ = (
                f"Red alert: you already have work booked {self.booked_summary()}. "
                f"Cancel and pick other dates, or Send to Shannon and she will work it out."
            )
            if hit and hit.level == "red":
                text_ += f" Also {hit.off_count} would be off {hit.half_day_label} ({self.names(hit)})."
            return text_
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
        """'Fri Dec 4 (3 off), Mon Dec 7 (2 cases booked)' for the red days only."""
        return ", ".join(
            f"{line['label']} ({line['booked'] or str(line['offCount']) + ' off'})"
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
            line = days.setdefault(hit.day, {"level": None, "offCount": 0, "ids": set(), "cases": 0, "visits": 0})
            if LEVEL_RANK[hit.level] > LEVEL_RANK[line["level"]]:
                line["level"] = hit.level
            line["offCount"] = max(line["offCount"], hit.off_count)
            line["ids"].update(hit.other_ids)
        for b in self.booked:
            line = days.setdefault(b["day"], {"level": None, "offCount": 1, "ids": set(), "cases": 0, "visits": 0})
            line["level"] = "red"
            line["cases"] += b["cases"]
            line["visits"] += b["visits"]
        out = []
        for day in sorted(days):
            line = days[day]
            out.append({
                "date": day.isoformat(),
                "label": day.strftime("%a %b %-d"),
                "level": line["level"],
                "offCount": max(line["offCount"], 1),
                "others": sorted(self.initials.get(sid, "?") for sid in line["ids"]),
                "booked": _booked_label(line["cases"], line["visits"]) if (line["cases"] or line["visits"]) else "",
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
        if self.booked:
            return f"RED: work already booked {self.booked_summary()}." + (
                f" Also {hit.off_count} off {hit.half_day_label} in {hit.group_name}." if hit and hit.level == "red" else ""
            )
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
    booked = []
    for row in db.execute(_BOOKED_SQL, {"card_ids": card_ids}).mappings().all():
        day = row["day"] if isinstance(row["day"], date) else date.fromisoformat(str(row["day"])[:10])
        booked.append({"day": day, "session": row["session"], "cases": int(row["cases"] or 0), "visits": int(row["visits"] or 0)})
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
        booked=booked,
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
    """A red request was saved: every active admin gets the red card (Don: any admin
    should see it); admins with day-off notices on also get a text."""
    from .push import notify_admins, send_sms
    from .models import AdminUser

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
        require_dayoff_opt_in=False,
        urgent_sms=False,
    )
    for admin in db.query(AdminUser).filter(AdminUser.is_active == True).all():  # noqa: E712
        if admin.notify_day_off_requests and admin.phone:
            send_sms(admin.phone, f"Red alert: time off: {surgeon.full_name} {span}. {result.admin_message()}")


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
    booked_days: dict[date, dict] = {}
    for b in result.booked:
        e = booked_days.setdefault(b["day"], {"cases": 0, "visits": 0})
        e["cases"] += b["cases"]
        e["visits"] += b["visits"]
    for day, e in booked_days.items():
        findings.append(DayOffFinding(
            severity="red",
            kind="time_off_capacity",
            date=day,
            message=f"RED: {day.strftime('%a %b %-d')} · {_booked_label(e['cases'], e['visits'])} for this doctor.",
            surgeon_message=result.surgeon_message(),
        ))
    findings.sort(key=lambda f: (-LEVEL_RANK[f.severity], f.date))
    return findings


# ---------------------------------------------------------------------------
# Auto-approval and red days ahead (Don, Nov 20)
# ---------------------------------------------------------------------------

def auto_approvable(surgeon: Surgeon, reason: str, result: CapacityResult) -> bool:
    """Inside the rules: a doctor's time off that is not red is approved on the spot.

    PAs and No Call requests still go to Shannon. Red waits for Shannon.
    """
    if (getattr(surgeon, "staff_type", None) or "physician") != "physician":
        return False
    if (reason or "").strip().lower() == "no call":
        return False
    return not result.is_red


_RED_DAYS_SQL = text(
    Path(__file__).with_name("sql").joinpath("time_off_red_days.sql").read_text()
)
_BOOKED_DAYS_SQL = text(
    Path(__file__).with_name("sql").joinpath("time_off_booked_days.sql").read_text()
)

RED_DAY_KIND = "time_off_red_day"


def red_day_runs(db: Session, start: date) -> list[dict]:
    """Red days from ``start`` on, merged into runs of consecutive weekdays per group."""
    from datetime import timedelta

    rows = db.execute(_RED_DAYS_SQL, {"start_day": start}).mappings().all()
    days: dict[tuple[int, date], dict] = {}
    for row in rows:
        day = row["day"] if isinstance(row["day"], date) else date.fromisoformat(str(row["day"])[:10])
        entry = days.setdefault((row["group_id"], day), {
            "group_id": row["group_id"],
            "group_name": row["group_name"],
            "red_at": row["red_at_off"],
            "day": day,
            "off": 0,
            "ids": set(),
        })
        entry["off"] = max(entry["off"], int(row["off_count"]))
        entry["ids"].add(int(row["surgeon_id"]))
    # Time off that sits on booked clinic or OR work is red for that doctor.
    for row in db.execute(_BOOKED_DAYS_SQL, {"start_day": start}).mappings().all():
        day = row["day"] if isinstance(row["day"], date) else date.fromisoformat(str(row["day"])[:10])
        sid = int(row["surgeon_id"])
        entry = days.setdefault((-sid, day), {
            "group_id": -sid,
            "group_name": "",
            "red_at": None,
            "day": day,
            "off": 0,
            "ids": {sid},
            "cases": 0,
            "visits": 0,
        })
        entry["cases"] = entry.get("cases", 0) + int(row["cases"] or 0)
        entry["visits"] = entry.get("visits", 0) + int(row["visits"] or 0)

    def next_weekday(d: date) -> date:
        d += timedelta(days=1)
        while d.weekday() >= 5:
            d += timedelta(days=1)
        return d

    runs: list[dict] = []
    for (group_id, day) in sorted(days, key=lambda k: (k[0], k[1])):
        entry = days[(group_id, day)]
        last = runs[-1] if runs else None
        if last and last["group_id"] == group_id and next_weekday(last["end"]) == day:
            last["end"] = day
            last["off"] = max(last["off"], entry["off"])
            last["ids"] |= entry["ids"]
            last["cases"] = last.get("cases", 0) + entry.get("cases", 0)
            last["visits"] = last.get("visits", 0) + entry.get("visits", 0)
        else:
            runs.append({**entry, "start": day, "end": day, "ids": set(entry["ids"])})
    ids = {sid for run in runs for sid in run["ids"]}
    initials = {s.id: s.initials for s in db.query(Surgeon).filter(Surgeon.id.in_(ids)).all()} if ids else {}
    for run in runs:
        run["initials"] = sorted(initials.get(sid, "?") for sid in run["ids"])
        if run["group_id"] < 0:
            run["group_name"] = f"{run['initials'][0]} has work booked during time off"
        run["key"] = f"{run['group_id']}|{run['start'].isoformat()}|{run['end'].isoformat()}"
    runs.sort(key=lambda r: (r["start"], r["group_name"]))
    return runs


def run_label(run: dict) -> str:
    return _run_label(run)


def _run_label(run: dict) -> str:
    start, end = run["start"], run["end"]
    if start == end:
        return start.strftime("%a %b %-d")
    return f"{start.strftime('%a %b %-d')} – {end.strftime('%a %b %-d')}"


def sync_red_day_alerts(db: Session, admin_user_id: int) -> int:
    """Give this admin one red card per red run from tomorrow on; drop cards no longer red.

    Covers red days however they arose (approved before the rules, group changes,
    Shannon approving a red request). Returns how many cards changed.
    """
    import json as _json

    from .models import AdminNotification, AdminUser
    from .scheduling_gate_service import practice_today

    admin = db.get(AdminUser, admin_user_id)
    # Don: any admin should see red days, whatever their notice settings.
    wants = bool(admin and admin.is_active)
    # Don: today is already known; alert from tomorrow on.
    from datetime import timedelta
    runs = red_day_runs(db, practice_today() + timedelta(days=1)) if wants else []
    current = {run["key"]: run for run in runs}
    existing = db.query(AdminNotification).filter(
        AdminNotification.admin_user_id == admin_user_id,
        AdminNotification.kind == RED_DAY_KIND,
    ).all()
    seen: set[str] = set()
    changed = 0
    for row in existing:
        try:
            key = (_json.loads(row.payload or "{}") or {}).get("key")
        except (TypeError, ValueError):
            key = None
        if key not in current or key in seen:
            db.delete(row)
            changed += 1
        else:
            seen.add(key)
    for key, run in current.items():
        if key in seen:
            continue
        if run["group_id"] < 0:
            title = f"Red: {run['group_name']}"
            body = f"{_run_label(run)}: {_booked_label(run.get('cases', 0), run.get('visits', 0))} while off."
        else:
            title = f"Red day: {run['group_name']}"
            body = f"{_run_label(run)}: {run['off']} off ({', '.join(run['initials'])}). Red at {run['red_at']}."
        db.add(AdminNotification(
            admin_user_id=admin_user_id,
            title=title,
            body=body,
            kind=RED_DAY_KIND,
            payload=_json.dumps({
                "key": key,
                "groupId": run["group_id"],
                "startDate": run["start"].isoformat(),
                "endDate": run["end"].isoformat(),
            }),
        ))
        changed += 1
    if changed:
        db.commit()
    return changed
