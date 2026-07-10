import os
import unittest
from datetime import date, time, timedelta
from unittest.mock import patch

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("SECRET_KEY", "test-secret")

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models import AdminUser, Base, Location, ScheduleChangeEvent, Surgeon
from app.or_block_service import (
    BlockORCreateInput,
    create_or_blocks,
    scheduler_digest_html,
    scheduler_digest_payload,
    scheduler_digest_recipients,
    send_scheduler_daily_digest,
)


class SchedulerDigestTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(bind=self.engine)
        self.Session = sessionmaker(bind=self.engine)

    def tearDown(self):
        Base.metadata.drop_all(bind=self.engine)
        self.engine.dispose()

    def test_recipients_require_opt_in_and_email(self):
        db = self.Session()
        try:
            db.add_all([
                AdminUser(
                    username="sched",
                    email="sched@example.com",
                    password_hash="x",
                    role="scheduler",
                    is_active=True,
                    notify_schedule_changes=True,
                ),
                AdminUser(
                    username="quiet",
                    email="quiet@example.com",
                    password_hash="x",
                    role="admin",
                    is_active=True,
                    notify_schedule_changes=False,
                ),
                AdminUser(
                    username="noemail",
                    email="",
                    password_hash="x",
                    role="admin",
                    is_active=True,
                    notify_schedule_changes=True,
                ),
            ])
            db.commit()
            recipients = scheduler_digest_recipients(db)
            self.assertEqual([row.username for row in recipients], ["sched"])
        finally:
            db.close()

    def test_payload_lists_open_blocks_and_recent_changes_without_patient_fields(self):
        db = self.Session()
        try:
            hospital = Location(
                name="Minneola OR",
                abbreviation="MN-OR",
                location_type="hospital",
                is_active=True,
            )
            db.add(hospital)
            db.flush()
            today = date(2026, 7, 10)
            create_or_blocks(db, BlockORCreateInput(
                name="Open AM",
                start_date=today,
                end_date=today,
                weekdays=[today.weekday()],
                location_ids=[hospital.id],
                session="am",
                start_time=time(7, 0),
                end_time=time(12, 0),
                recurrence="once",
            ))
            db.add(ScheduleChangeEvent(
                event_type="block_or_assigned",
                title="Block OR assigned",
                body="MN-OR - 07:00 - 1 Case JF",
                date=today,
            ))
            db.commit()

            payload = scheduler_digest_payload(db, today=today)
            self.assertEqual(len(payload["openBlocks"]), 1)
            self.assertEqual(payload["openBlocks"][0]["locationAbbreviation"], "MN-OR")
            self.assertGreaterEqual(len(payload["changes"]), 1)
            blob = scheduler_digest_html(payload).lower()
            for banned in ("patient", "dob", "mrn", "phone", "ssn"):
                self.assertNotIn(banned, blob)
            self.assertIn("mn-or", blob)
            self.assertIn("block or assigned", blob)
        finally:
            db.close()

    def test_send_digest_counts_sent_emails(self):
        db = self.Session()
        try:
            db.add(AdminUser(
                username="admin",
                email="admin@example.com",
                password_hash="x",
                role="admin",
                is_active=True,
                notify_schedule_changes=True,
            ))
            db.commit()
            with patch("app.or_block_service.send_email", return_value=True) as send_email:
                result = send_scheduler_daily_digest(db)
            self.assertEqual(result["recipients"], 1)
            self.assertEqual(result["sent"], 1)
            send_email.assert_called_once()
            kwargs = send_email.call_args.kwargs
            self.assertEqual(kwargs["to_email"], "admin@example.com")
            self.assertIn("digest", kwargs["subject"].lower())
        finally:
            db.close()


if __name__ == "__main__":
    unittest.main()
