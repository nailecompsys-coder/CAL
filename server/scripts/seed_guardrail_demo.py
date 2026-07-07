#!/usr/bin/env python3
"""Seed local-only scheduling guardrail demo data."""

from __future__ import annotations

import os
import sys
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

os.environ.setdefault("SECRET_KEY", "demo-run-only")
os.environ.setdefault("BASE_URL", "http://127.0.0.1:3005")
os.environ.setdefault("VAPID_PRIVATE_KEY", "demo-placeholder")
os.environ.setdefault("VAPID_PUBLIC_KEY", "demo-placeholder")
os.environ.setdefault("VAPID_EMAIL", "demo@example.com")

from app import migrate_scheduling_guardrails  # noqa: E402
from app.auth import hash_password  # noqa: E402
from app.database import Base, SessionLocal, engine  # noqa: E402
from app.models import (  # noqa: E402
    AdminUser,
    ClinicGroup,
    ClinicGroupMember,
    ClinicSchedule,
    DayOff,
    Location,
    Meeting,
    MeetingAttendee,
    MagicLink,
    Surgeon,
    SurgicalBlock,
    SurgicalCase,
)
from app.routers.surgeon_otp import _hash_otp  # noqa: E402
from app.scheduling_guardrails_service import store_dayoff_findings  # noqa: E402


DEMO_DOMAIN = "guardrail-demo.local"


def require_local_db() -> None:
    db_url = os.environ.get("DATABASE_URL", "")
    host = (urlparse(db_url).hostname or "").lower()
    allowed = {"localhost", "127.0.0.1", "::1", ""}
    if host not in allowed and os.environ.get("ALLOW_LOCAL_DEMO_DATA") != "1":
        raise SystemExit(
            f"Refusing to seed demo data into non-local database host '{host}'. "
            "Set ALLOW_LOCAL_DEMO_DATA=1 only for an intentional dev DB."
        )


def next_weekday(start: date, weekday: int) -> date:
    delta = (weekday - start.weekday()) % 7
    if delta == 0:
        delta = 7
    return start + timedelta(days=delta)


def surgeon(db, first, last, sort_order) -> Surgeon:
    email = f"{first.lower()}.{last.lower()}@{DEMO_DOMAIN}"
    row = db.query(Surgeon).filter(Surgeon.email == email).first()
    if row:
        return row
    row = Surgeon(
        first_name=first,
        last_name=last,
        email=email,
        staff_type="physician",
        sort_order=sort_order,
        is_active=True,
        color="#ffffff",
    )
    db.add(row)
    db.flush()
    return row


def location(db, name, abbreviation, loc_type="hospital") -> Location:
    row = db.query(Location).filter(Location.name == name).first()
    if row:
        return row
    row = Location(
        name=name,
        abbreviation=abbreviation,
        location_type=loc_type,
        color="#9ad7c7" if loc_type == "clinic" else "#b7d7f2",
        is_active=True,
    )
    db.add(row)
    db.flush()
    return row


def clinic_group(db, name, abbreviation, max_off) -> ClinicGroup:
    row = db.query(ClinicGroup).filter(ClinicGroup.name == name).first()
    if not row:
        row = ClinicGroup(name=name, abbreviation=abbreviation, max_approved_off_per_day=max_off, is_active=True)
        db.add(row)
        db.flush()
    else:
        row.abbreviation = abbreviation
        row.max_approved_off_per_day = max_off
        row.is_active = True
    return row


def assign_group(db, group, surgeons):
    for s in surgeons:
        exists = db.query(ClinicGroupMember).filter(
            ClinicGroupMember.clinic_group_id == group.id,
            ClinicGroupMember.surgeon_id == s.id,
        ).first()
        if not exists:
            db.add(ClinicGroupMember(clinic_group_id=group.id, surgeon_id=s.id))


def reset_demo(db):
    demo_surgeons = db.query(Surgeon).filter(Surgeon.email.like(f"%@{DEMO_DOMAIN}")).all()
    for s in demo_surgeons:
        db.delete(s)
    for loc_name in ["Demo Winter Garden OR", "Demo Lake Mary OR", "Demo Main Office"]:
        loc = db.query(Location).filter(Location.name == loc_name).first()
        if loc:
            db.delete(loc)
    scheduler = db.query(AdminUser).filter(AdminUser.username == "demo.scheduler").first()
    if scheduler:
        db.delete(scheduler)
    admin = db.query(AdminUser).filter(AdminUser.username == "demo.admin").first()
    if admin:
        db.delete(admin)
    db.commit()


def seed():
    require_local_db()
    Base.metadata.create_all(bind=engine)
    migrate_scheduling_guardrails.run_migration()

    today = date.today()
    capacity_day = next_weekday(today, 2)  # Wednesday
    block_day = next_weekday(today, 3)  # Thursday
    db = SessionLocal()
    try:
        reset_demo(db)

        wg1 = surgeon(db, "Walter", "Gardenone", 901)
        wg2 = surgeon(db, "Nora", "Gardentwo", 902)
        wg3 = surgeon(db, "Paula", "Gardenthree", 903)
        lm1 = surgeon(db, "Liam", "Maryone", 904)
        lm2 = surgeon(db, "Sara", "Marytwo", 905)
        block_doc = surgeon(db, "Owen", "Blockdoc", 906)

        wg_or = location(db, "Demo Winter Garden OR", "DWG", "hospital")
        lm_or = location(db, "Demo Lake Mary OR", "DLM", "hospital")
        main_office = location(db, "Demo Main Office", "DMO", "clinic")

        wg = clinic_group(db, "Winter Garden", "WG", 2)
        lm = clinic_group(db, "Lake Mary", "LM", 1)
        assign_group(db, wg, [wg1, wg2, wg3, block_doc])
        assign_group(db, lm, [lm1, lm2])

        wg_pending = DayOff(surgeon_id=wg3.id, start_date=capacity_day, end_date=capacity_day, reason="Demo WG warning request", status="pending")
        lm_pending = DayOff(surgeon_id=lm2.id, start_date=capacity_day, end_date=capacity_day, reason="Demo LM warning request", status="pending")
        db.add_all([
            DayOff(surgeon_id=wg1.id, start_date=capacity_day, end_date=capacity_day, reason="Demo approved WG", status="approved"),
            DayOff(surgeon_id=wg2.id, start_date=capacity_day, end_date=capacity_day, reason="Demo approved WG", status="approved"),
            DayOff(surgeon_id=lm1.id, start_date=capacity_day, end_date=capacity_day, reason="Demo approved LM", status="approved"),
            wg_pending,
            lm_pending,
        ])
        db.flush()
        store_dayoff_findings(db, wg_pending)
        store_dayoff_findings(db, lm_pending)

        db.add(SurgicalBlock(
            surgeon_id=block_doc.id,
            location_id=wg_or.id,
            day_of_week=block_day.weekday(),
            start_time=time(7, 30),
            end_time=time(12, 0),
            recurrence="weekly",
            notes="Demo block clear in AM",
        ))
        db.add_all([
            SurgicalCase(
                surgeon_id=block_doc.id,
                date=block_day,
                start_time=time(8, 0),
                end_time=time(8, 45),
                patient_name="DEMO HIDDEN",
                procedure="Demo clear in-block case",
                location_id=wg_or.id,
                status="scheduled",
            ),
            SurgicalCase(
                surgeon_id=block_doc.id,
                date=block_day,
                start_time=time(15, 0),
                end_time=time(15, 45),
                patient_name="DEMO HIDDEN",
                procedure="Demo outside block warning",
                location_id=wg_or.id,
                status="scheduled",
            ),
        ])
        db.add(ClinicSchedule(
            surgeon_id=block_doc.id,
            location_id=main_office.id,
            date=block_day,
            session="am",
            assignment_type="assigned",
            notes="Demo clinic overlap warning",
        ))
        db.add(DayOff(
            surgeon_id=block_doc.id,
            start_date=block_day + timedelta(days=1),
            end_date=block_day + timedelta(days=1),
            reason="Demo approved off for case warning",
            status="approved",
        ))
        db.add(SurgicalCase(
            surgeon_id=block_doc.id,
            date=block_day + timedelta(days=1),
            start_time=time(9, 0),
            end_time=time(9, 45),
            patient_name="DEMO HIDDEN",
            procedure="Demo day-off overlap warning",
            location_id=lm_or.id,
            status="scheduled",
        ))
        meeting = Meeting(
            title="Demo assigned meeting",
            date=block_day + timedelta(days=2),
            start_time=time(10, 0),
            end_time=time(11, 0),
            location_text="Demo conference room",
        )
        db.add(meeting)
        db.flush()
        db.add(MeetingAttendee(meeting_id=meeting.id, surgeon_id=block_doc.id))
        db.add(SurgicalCase(
            surgeon_id=block_doc.id,
            date=block_day + timedelta(days=2),
            start_time=time(10, 15),
            end_time=time(10, 45),
            patient_name="DEMO HIDDEN",
            procedure="Demo meeting overlap warning",
            location_id=wg_or.id,
            status="scheduled",
        ))
        db.add(AdminUser(
            username="demo.admin",
            email=f"admin@{DEMO_DOMAIN}",
            password_hash=hash_password("DemoAdmin2026!"),
            role="admin",
            is_active=True,
        ))
        db.add(AdminUser(
            username="demo.scheduler",
            email=f"scheduler@{DEMO_DOMAIN}",
            password_hash=hash_password("DemoScheduler2026!"),
            role="scheduler",
            is_active=True,
        ))
        db.add(MagicLink(
            surgeon_id=lm2.id,
            token_hash=_hash_otp("111111") + ":otp",
            expires_at=datetime.now(timezone.utc) + timedelta(days=7),
        ))
        db.commit()
        print("Guardrail demo data seeded.")
        print(f"Capacity warning date: {capacity_day.isoformat()}")
        print(f"Surgical block warning date: {block_day.isoformat()}")
        print("Admin login: demo.admin / DemoAdmin2026!")
        print("Scheduler login: demo.scheduler / DemoScheduler2026!")
        print(f"iOS demo sign-in: {lm2.email} / 111111")
    finally:
        db.close()


if __name__ == "__main__":
    seed()
