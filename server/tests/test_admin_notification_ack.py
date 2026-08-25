import json
import os
import unittest
from datetime import date, timedelta
from types import SimpleNamespace

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("SECRET_KEY", "test-secret")

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.admin_notification_ack import ack_informational_notification, notification_is_informational
from app.grok_lookahead_service import (
    build_grok_lookahead,
    reconcile_stale_call_coverage_notifications,
)
from app.models import (
    AdminNotification,
    AdminUser,
    Base,
    CallCoverage,
    CallGroup,
    CallRotation,
    DayOff,
    Surgeon,
)


class NotificationAckTest(unittest.TestCase):
    def test_cal_bot_card_is_informational(self):
        row = SimpleNamespace(kind="clippy", title="Cal-BOT", body="Looks like you are scheduling.")
        self.assertTrue(notification_is_informational(row))

    def test_pending_day_off_is_not_informational(self):
        row = SimpleNamespace(kind="day_off_request", title="Pending Request", body="Jason requested Sep 18.")
        self.assertFalse(notification_is_informational(row))

    def test_clicking_informational_card_deletes_it(self):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        db = sessionmaker(bind=engine)()
        try:
            admin = AdminUser(username="don", email="don@example.com", password_hash="x", is_active=True)
            db.add(admin)
            db.commit()
            db.refresh(admin)
            note = AdminNotification(
                admin_user_id=admin.id,
                title="Cal-BOT",
                body="Looks like you are scheduling.",
                kind="clippy",
                payload=json.dumps({"href": "/admin/clinic-schedule"}),
            )
            db.add(note)
            db.commit()
            note_id = note.id
            href = ack_informational_notification(db, admin.id, note_id)
            self.assertEqual(href, "/admin/clinic-schedule")
            self.assertIsNone(db.get(AdminNotification, note_id))
        finally:
            db.close()
            engine.dispose()

    def test_ack_does_not_delete_a_real_conflict_card(self):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        db = sessionmaker(bind=engine)()
        try:
            admin = AdminUser(username="don", email="don2@example.com", password_hash="x", is_active=True)
            db.add(admin)
            db.commit()
            db.refresh(admin)
            note = AdminNotification(
                admin_user_id=admin.id,
                title="Call coverage schedule conflict",
                body="still a clash",
                kind="call_coverage_conflict",
                payload=json.dumps({"rotationId": 651, "href": "/admin/call-schedule"}),
            )
            db.add(note)
            db.commit()
            note_id = note.id
            href = ack_informational_notification(db, admin.id, note_id)
            self.assertIn("/admin/call-schedule", href)
            self.assertIsNotNone(db.get(AdminNotification, note_id))
        finally:
            db.close()
            engine.dispose()


class StaleCallCoverageCardTest(unittest.TestCase):
    def test_grok_drops_coverage_card_when_time_off_is_gone(self):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        db = sessionmaker(bind=engine)()
        try:
            admin = AdminUser(username="don", email="don@example.com", password_hash="x", is_active=True)
            covering = Surgeon(
                first_name="Jason", last_name="Boardman",
                email="jb@example.com", is_active=True, staff_type="physician",
            )
            original = Surgeon(
                first_name="Alex", last_name="Schroeder",
                email="as@example.com", is_active=True, staff_type="physician",
            )
            group = CallGroup(name="Winter Garden", sort_order=1)
            db.add_all([admin, covering, original, group])
            db.commit()
            day = date.today() + timedelta(days=12)
            rotation = CallRotation(
                surgeon_id=original.id, date=day, call_group_id=group.id, rotation_type="primary",
            )
            db.add(rotation)
            db.flush()
            db.add(CallCoverage(
                call_rotation_id=rotation.id,
                original_surgeon_id=original.id,
                covering_surgeon_id=covering.id,
                requested_by_surgeon_id=original.id,
                status="active",
            ))
            note = AdminNotification(
                admin_user_id=admin.id,
                title="Call coverage schedule conflict",
                body="Jason Boardman covering Sep 18: JB: Approved day off on Sep 18",
                kind="call_coverage_conflict",
                payload=json.dumps({
                    "rotationId": rotation.id,
                    "coveringSurgeonId": covering.id,
                    "date": day.isoformat(),
                }),
            )
            db.add(note)
            db.commit()
            note_id = note.id
            payload = build_grok_lookahead(db, today=date.today())
            self.assertGreaterEqual(payload["clearedCount"], 1)
            self.assertIsNone(db.get(AdminNotification, note_id))
            self.assertEqual(reconcile_stale_call_coverage_notifications(db), 0)
        finally:
            db.close()
            engine.dispose()

    def test_keeps_card_while_covering_doctor_is_still_off(self):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        db = sessionmaker(bind=engine)()
        try:
            admin = AdminUser(username="don", email="don@example.com", password_hash="x", is_active=True)
            covering = Surgeon(
                first_name="Jason", last_name="Boardman",
                email="jb2@example.com", is_active=True, staff_type="physician",
            )
            original = Surgeon(
                first_name="Alex", last_name="Schroeder",
                email="as2@example.com", is_active=True, staff_type="physician",
            )
            group = CallGroup(name="Winter Garden", sort_order=1)
            db.add_all([admin, covering, original, group])
            db.commit()
            day = date.today() + timedelta(days=8)
            rotation = CallRotation(
                surgeon_id=original.id, date=day, call_group_id=group.id, rotation_type="primary",
            )
            db.add(rotation)
            db.flush()
            db.add(CallCoverage(
                call_rotation_id=rotation.id,
                original_surgeon_id=original.id,
                covering_surgeon_id=covering.id,
                requested_by_surgeon_id=original.id,
                status="active",
            ))
            db.add(DayOff(
                surgeon_id=covering.id, start_date=day, end_date=day,
                status="approved", reason="Day Off",
            ))
            note = AdminNotification(
                admin_user_id=admin.id,
                title="Call coverage schedule conflict",
                body="still real",
                kind="call_coverage_conflict",
                payload=json.dumps({
                    "rotationId": rotation.id,
                    "coveringSurgeonId": covering.id,
                    "date": day.isoformat(),
                }),
            )
            db.add(note)
            db.commit()
            note_id = note.id
            self.assertEqual(reconcile_stale_call_coverage_notifications(db), 0)
            self.assertIsNotNone(db.get(AdminNotification, note_id))
        finally:
            db.close()
            engine.dispose()
