"""Don's rule 10: a patient on an OFF / approved-OFF day is a conflict.

The line is still entered (Epic is the source). Shannon and Don get an admin
portal notice through the existing AdminNotification mechanism. The notice is
written in the apply transaction (no commit here) and never goes to surgeons.
"""

from __future__ import annotations

import json
import os
from collections import defaultdict
from datetime import date

from sqlalchemy import text
from sqlalchemy.orm import Session

from .fax_ingest_guardrails import approved_day_off_for_ingest
from .models import AdminNotification, AdminUser, Surgeon

NOTICE_KIND = "ingest_day_off_conflict"
DEFAULT_RECIPIENTS = "szeh,dnaile"


def conflict_recipients(db: Session) -> list[AdminUser]:
    names = [
        name.strip().lower()
        for name in os.getenv("FAX_CONFLICT_NOTIFY_USERNAMES", DEFAULT_RECIPIENTS).split(",")
        if name.strip()
    ]
    if not names:
        return []
    return (
        db.query(AdminUser)
        .filter(AdminUser.username.in_(names), AdminUser.is_active == True)  # noqa: E712
        .order_by(AdminUser.id)
        .all()
    )


def _as_date(value) -> date:
    return value if isinstance(value, date) else date.fromisoformat(str(value)[:10])


def off_day_conflicts(db: Session, run_id: int) -> list[dict]:
    """Applicable rows that land on an OFF card or an approved day off, grouped by surgeon/day."""
    rows = db.execute(text("""
        SELECT fax_row.surgeon_id, fax_row.case_date, fax_row.session, fax_row.start_time,
               decision.reason_code
        FROM fax_ingest_rows_applicable applicable
        JOIN fax_ingest_rows fax_row ON fax_row.id = applicable.fax_row_id
        JOIN fax_row_decisions decision ON decision.fax_row_id = fax_row.id
        WHERE applicable.run_id = :run_id
        ORDER BY fax_row.surgeon_id, fax_row.case_date, fax_row.session, fax_row.id
    """), {"run_id": run_id}).all()
    grouped: dict[tuple[int, date], dict] = defaultdict(lambda: {"lines": 0, "sessions": set(), "dayOffId": None})
    for surgeon_id, case_date, session, start_time, reason in rows:
        day = _as_date(case_date)
        day_off = None
        if reason != "off_collision":
            day_off = approved_day_off_for_ingest(db, surgeon_id=surgeon_id, day=day, session=session)
            if day_off is None:
                continue
        item = grouped[(surgeon_id, day)]
        item["lines"] += 1
        item["sessions"].add(session)
        if day_off is not None:
            item["dayOffId"] = day_off.id
    return [
        {"surgeonId": sid, "date": day.isoformat(), "lines": v["lines"],
         "sessions": sorted(v["sessions"]), "dayOffId": v["dayOffId"]}
        for (sid, day), v in sorted(grouped.items())
    ]


def notify_off_day_conflicts(db: Session, *, run_id: int, source_fax_id: int) -> list[dict]:
    conflicts = off_day_conflicts(db, run_id)
    if not conflicts:
        return []
    recipients = conflict_recipients(db)
    for conflict in conflicts:
        surgeon = db.get(Surgeon, conflict["surgeonId"])
        name = f"{surgeon.first_name} {surgeon.last_name}" if surgeon else f"surgeon {conflict['surgeonId']}"
        day = date.fromisoformat(conflict["date"])
        title = "Fax ingest: patient on an OFF day"
        body = (
            f"{name} · {day.strftime('%m/%d/%Y')} · {'/'.join(s.upper() for s in conflict['sessions'])}: "
            f"fax {source_fax_id} entered {conflict['lines']} line(s) on a day marked OFF. Please review."
        )
        payload = {
            "flagType": NOTICE_KIND,
            "fingerprint": f"{NOTICE_KIND}|{source_fax_id}|{conflict['surgeonId']}|{conflict['date']}",
            "href": f"/admin/schedule?date={conflict['date']}",
            "sourceFaxId": source_fax_id,
            "runId": run_id,
            **conflict,
        }
        for admin in recipients:
            db.add(AdminNotification(
                admin_user_id=admin.id, title=title, body=body, kind=NOTICE_KIND, payload=json.dumps(payload),
            ))
    db.flush()
    return conflicts
