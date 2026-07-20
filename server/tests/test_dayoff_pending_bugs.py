"""Regression: pending-only duplicate gate + stale admin notification cleanup."""
import json
import os
import unittest
from datetime import date, datetime

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("SECRET_KEY", "test-secret")

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.admin_dayoff_service import approve_dayoff, deny_dayoff
from app.admin_settings_page_service import recent_admin_notifications, reconcile_stale_dayoff_notifications
from app.models import AdminNotification, AdminUser, Base, DayOff, Surgeon
from app.scheduling_gate_service import (
    purge_newer_duplicates_for_request,
    reject_if_duplicate_day_off,
)


class DayOffPendingBugsTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)
        self.db = self.Session()
        self.surgeon = Surgeon(
            first_name="Jason",
            last_name="Boardman",
            email="boardman@example.com",
            is_active=True,
            staff_type="physician",
        )
        self.admin = AdminUser(
            username="shannon",
            email="shannon@example.com",
            password_hash="x",
            is_active=True,
        )
        self.db.add_all([self.surgeon, self.admin])
        self.db.commit()
        self.db.refresh(self.surgeon)
        self.db.refresh(self.admin)

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def test_extension_over_approved_is_not_hard_rejected(self):
        approved = DayOff(
            surgeon_id=self.surgeon.id,
            start_date=date(2026, 8, 1),
            end_date=date(2026, 8, 9),
            status="approved",
            reason="vacation",
        )
        self.db.add(approved)
        self.db.commit()

        from app.scheduling_gate_service import day_off_overlap_advisory

        note = day_off_overlap_advisory(
            self.db, self.surgeon.id, date(2026, 8, 6), date(2026, 8, 18)
        )
        self.assertIsNotNone(note)
        self.assertIn("overlap", note.lower())
        # Still never hard-blocks.
        blocked = reject_if_duplicate_day_off(
            self.db, self.surgeon.id, date(2026, 8, 6), date(2026, 8, 18), as_http=True
        )
        self.assertIsNotNone(blocked)  # finds overlap
        # as_http must not raise
        reject_if_duplicate_day_off(
            self.db, self.surgeon.id, date(2026, 8, 6), date(2026, 8, 18), as_http=True
        )

    def test_overlapping_pending_is_advisory_not_rejected(self):
        from app.scheduling_gate_service import day_off_overlap_advisory

        pending = DayOff(
            surgeon_id=self.surgeon.id,
            start_date=date(2026, 8, 6),
            end_date=date(2026, 8, 18),
            status="pending",
            reason="vacation",
        )
        self.db.add(pending)
        self.db.commit()
        note = day_off_overlap_advisory(
            self.db, self.surgeon.id, date(2026, 8, 10), date(2026, 8, 12)
        )
        self.assertIsNotNone(note)
        self.assertIn("Shannon", note)

    def test_purge_does_not_delete_pending_when_approved_overlaps(self):
        approved = DayOff(
            surgeon_id=self.surgeon.id,
            start_date=date(2026, 8, 1),
            end_date=date(2026, 8, 9),
            status="approved",
            reason="vacation",
        )
        pending = DayOff(
            surgeon_id=self.surgeon.id,
            start_date=date(2026, 8, 6),
            end_date=date(2026, 8, 18),
            status="pending",
            reason="extension",
        )
        self.db.add_all([approved, pending])
        self.db.commit()
        self.db.refresh(pending)

        removed = purge_newer_duplicates_for_request(
            self.db,
            self.surgeon.id,
            date(2026, 8, 6),
            date(2026, 8, 18),
            keep_id=pending.id,
        )
        self.assertEqual(removed, 0)
        still = self.db.get(DayOff, pending.id)
        self.assertIsNotNone(still)
        self.assertEqual(still.status, "pending")

    def test_stale_pending_notifications_cleared_after_approve(self):
        dayoff = DayOff(
            surgeon_id=self.surgeon.id,
            start_date=date(2026, 9, 1),
            end_date=date(2026, 9, 3),
            status="pending",
            reason="trip",
        )
        self.db.add(dayoff)
        self.db.commit()
        self.db.refresh(dayoff)

        note = AdminNotification(
            admin_user_id=self.admin.id,
            title="Pending Request",
            body="Jason Boardman requested Sep 1 to Sep 3.",
            kind="day_off_request",
            payload=json.dumps({"dayOffId": dayoff.id, "surgeonId": self.surgeon.id}),
        )
        self.db.add(note)
        self.db.commit()

        with unittest.mock.patch("app.admin_dayoff_service.store_dayoff_findings"), \
             unittest.mock.patch("app.admin_dayoff_service.send_push_to_surgeon"), \
             unittest.mock.patch("app.admin_dayoff_service.log_schedule_change"):
            approve_dayoff(self.db, dayoff.id, self.admin.id)

        self.db.refresh(dayoff)
        self.db.refresh(note)
        self.assertEqual(dayoff.status, "approved")
        self.assertIsNotNone(note.read_at)

    def test_dashboard_hides_stale_dayoff_notifications(self):
        # Notification points at already-approved day off (Shannon handled it).
        dayoff = DayOff(
            surgeon_id=self.surgeon.id,
            start_date=date(2026, 7, 17),
            end_date=date(2026, 7, 17),
            status="approved",
            reason="done",
        )
        self.db.add(dayoff)
        self.db.commit()
        self.db.refresh(dayoff)
        note = AdminNotification(
            admin_user_id=self.admin.id,
            title="Pending Request",
            body="stale",
            kind="day_off_request",
            payload=json.dumps({"dayOffId": dayoff.id}),
        )
        self.db.add(note)
        self.db.commit()

        cleared = reconcile_stale_dayoff_notifications(self.db, self.admin.id)
        self.assertEqual(cleared, 1)
        rows = recent_admin_notifications(self.db, self.admin.id, limit=8)
        unread = [r for r in rows if r.read_at is None and r.kind == "day_off_request"]
        self.assertEqual(unread, [])


# late import for patch in approve test
import unittest.mock  # noqa: E402


if __name__ == "__main__":
    unittest.main()
