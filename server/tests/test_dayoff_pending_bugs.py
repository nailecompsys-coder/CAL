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
from app.admin_settings_page_service import (
    recent_admin_notifications,
    reconcile_stale_dayoff_notifications,
    reconcile_stale_schedule_flag_notifications,
)
from app.models import AdminNotification, AdminUser, Base, DayOff, ScheduleChangeEvent, Surgeon
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

    def test_exact_pending_duplicate_is_reused_not_recreated(self):
        from app.native_request_off_helpers import NativeRequestOffInput
        from app.native_request_off_service import create_native_request_off

        start = date(2026, 12, 8)
        end = date(2026, 12, 12)
        first = DayOff(
            surgeon_id=self.surgeon.id,
            start_date=start,
            end_date=end,
            status="pending",
            reason="Day Off",
        )
        self.db.add(first)
        self.db.commit()
        self.db.refresh(first)

        with unittest.mock.patch("app.native_request_off_service.send_native_push_to_surgeon"), \
             unittest.mock.patch("app.native_request_off_service.notify_admins"), \
             unittest.mock.patch("app.native_request_off_service.log_schedule_change"), \
             unittest.mock.patch("app.time_off_email_service.send_email", return_value=True), \
             unittest.mock.patch("app.native_request_off_service.store_dayoff_findings", return_value=[]):
            result = create_native_request_off(
                self.db,
                self.surgeon,
                NativeRequestOffInput(start_date=start, end_date=end, reason="Day Off"),
            )

        self.assertTrue(result["ok"])
        self.assertEqual(result["request"]["id"], first.id)
        self.assertIn("already pending", result["warnings"][0].lower())
        self.assertEqual(
            self.db.query(DayOff).filter(DayOff.surgeon_id == self.surgeon.id).count(),
            1,
        )

    def test_purge_exact_pending_duplicates(self):
        from app.scheduling_gate_service import purge_exact_pending_duplicates

        start = date(2026, 12, 8)
        end = date(2026, 12, 12)
        keep = DayOff(
            surgeon_id=self.surgeon.id,
            start_date=start,
            end_date=end,
            status="pending",
            reason="Day Off",
        )
        dup = DayOff(
            surgeon_id=self.surgeon.id,
            start_date=start,
            end_date=end,
            status="pending",
            reason="Day Off",
        )
        other = DayOff(
            surgeon_id=self.surgeon.id,
            start_date=date(2026, 11, 26),
            end_date=date(2026, 11, 30),
            status="pending",
            reason="Day Off",
        )
        self.db.add_all([keep, dup, other])
        self.db.commit()
        self.db.refresh(keep)
        self.db.refresh(dup)
        self.db.refresh(other)

        removed = purge_exact_pending_duplicates(
            self.db, self.surgeon.id, start, end, keep_id=keep.id
        )
        self.assertEqual(removed, 1)
        self.assertIsNone(self.db.get(DayOff, dup.id))
        self.assertIsNotNone(self.db.get(DayOff, keep.id))
        self.assertIsNotNone(self.db.get(DayOff, other.id))

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
        note_id = note.id

        cleared = reconcile_stale_dayoff_notifications(self.db, self.admin.id)
        self.assertEqual(cleared, 1)
        self.assertIsNone(self.db.get(AdminNotification, note_id))
        rows = recent_admin_notifications(self.db, self.admin.id, limit=8)
        self.assertEqual([r for r in rows if r.kind == "day_off_request"], [])

    def test_approve_removes_pending_notification_cards(self):
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
        note_id = note.id

        with unittest.mock.patch("app.admin_dayoff_service.store_dayoff_findings"), \
             unittest.mock.patch("app.admin_dayoff_service.send_push_to_surgeon"), \
             unittest.mock.patch("app.admin_dayoff_service.log_schedule_change"), \
             unittest.mock.patch("app.time_off_email_service.send_email", return_value=True):
            approve_dayoff(self.db, dayoff.id, self.admin.id)

        self.assertIsNone(self.db.get(AdminNotification, note_id))

    def test_approve_and_deny_email_the_surgeon(self):
        dayoff = DayOff(
            surgeon_id=self.surgeon.id,
            start_date=date(2026, 10, 1),
            end_date=date(2026, 10, 2),
            status="pending",
            reason="Vacation",
        )
        self.db.add(dayoff)
        self.db.commit()
        self.db.refresh(dayoff)

        with unittest.mock.patch("app.admin_dayoff_service.store_dayoff_findings"), \
             unittest.mock.patch("app.admin_dayoff_service.send_push_to_surgeon"), \
             unittest.mock.patch("app.admin_dayoff_service.log_schedule_change"), \
             unittest.mock.patch("app.time_off_email_service.send_email", return_value=True) as emailed:
            approve_dayoff(self.db, dayoff.id, self.admin.id)

        emailed.assert_called_once()
        self.assertEqual(emailed.call_args.kwargs["to_email"], "boardman@example.com")
        self.assertIn("Time off approved:", emailed.call_args.kwargs["subject"])
        self.assertIn("approved", emailed.call_args.kwargs["html_body"].lower())

        denied = DayOff(
            surgeon_id=self.surgeon.id,
            start_date=date(2026, 11, 1),
            end_date=date(2026, 11, 1),
            status="pending",
            reason="CME",
            admin_note="Coverage gap",
        )
        self.db.add(denied)
        self.db.commit()
        self.db.refresh(denied)

        with unittest.mock.patch("app.admin_dayoff_service.send_push_to_surgeon"), \
             unittest.mock.patch("app.admin_dayoff_service.log_schedule_change"), \
             unittest.mock.patch("app.time_off_email_service.send_email", return_value=True) as emailed:
            deny_dayoff(self.db, denied.id, "Coverage gap", self.admin.id)

        emailed.assert_called_once()
        self.assertEqual(emailed.call_args.kwargs["to_email"], "boardman@example.com")
        self.assertIn("Time off denied:", emailed.call_args.kwargs["subject"])
        self.assertIn("Coverage gap", emailed.call_args.kwargs["html_body"])

    def test_past_schedule_flags_are_dropped(self):
        note = AdminNotification(
            admin_user_id=self.admin.id,
            title="Scheduling flag · Block OR",
            body="Owen Kieran · 08-10-26 · AP-OR 07:15-09:55: Already assigned Block OR",
            kind="schedule_flag",
            payload=json.dumps({"blockId": 1, "surgeonId": 1, "date": "2026-08-10"}),
        )
        event = ScheduleChangeEvent(
            event_type="desk_or_schedule_flag",
            title="Desk OR schedule flag",
            body="Nadia Froehling · 08-11-26 · MN-OR: Already assigned Block OR",
            date=date(2026, 8, 11),
            payload=json.dumps({"blockId": 2, "date": "2026-08-11"}),
        )
        self.db.add_all([note, event])
        self.db.commit()
        note_id, event_id = note.id, event.id
        with unittest.mock.patch(
            "app.scheduling_gate_service.practice_today",
            return_value=date(2026, 8, 14),
        ):
            removed = reconcile_stale_schedule_flag_notifications(self.db, self.admin.id)
        self.assertGreaterEqual(removed, 2)
        self.assertIsNone(self.db.get(AdminNotification, note_id))
        self.assertIsNone(self.db.get(ScheduleChangeEvent, event_id))


# late import for patch in approve test
import unittest.mock  # noqa: E402


if __name__ == "__main__":
    unittest.main()
