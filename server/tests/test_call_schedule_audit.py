import os
import unittest
from datetime import date, timedelta
from unittest.mock import patch

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("SECRET_KEY", "test-secret")

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.admin_call_schedule_action_service import assign_rotation, clear_rotation
from app.call_schedule_audit_service import recent_call_schedule_audit_logs
from app.models import AdminUser, Base, CallGroup, CallRotation, CallScheduleAuditLog, Surgeon
from app.native_call_coverage_service import assign_admin_call_coverage, assign_native_call_coverage


class CallScheduleAuditTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(bind=self.engine)
        self.Session = sessionmaker(bind=self.engine)

    def tearDown(self):
        Base.metadata.drop_all(bind=self.engine)
        self.engine.dispose()

    def _seed(self, db):
        admin = AdminUser(
            username="shannon",
            email="shannon@example.com",
            password_hash="x",
            first_name="Shannon",
            last_name="Admin",
            role="admin",
        )
        a = Surgeon(first_name="Chris", last_name="Johnson", email="cj@example.com", is_active=True, staff_type="physician")
        b = Surgeon(first_name="Alex", last_name="Schroeder", email="as@example.com", is_active=True, staff_type="physician")
        group = CallGroup(name="Winter Garden", sort_order=1)
        db.add_all([admin, a, b, group])
        db.commit()
        return admin, a, b, group

    def test_assign_and_clear_write_audit(self):
        db = self.Session()
        try:
            admin, chris, _, group = self._seed(db)
            day = date.today() + timedelta(days=2)
            with patch("app.admin_call_schedule_action_service.send_push_to_surgeon"):
                assign_rotation(db, day, chris.id, group.id, admin=admin)
            rows = db.query(CallScheduleAuditLog).all()
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0].action, "assign")
            self.assertEqual(rows[0].source, "portal")
            self.assertEqual(rows[0].to_surgeon_id, chris.id)
            self.assertEqual(rows[0].actor_admin_id, admin.id)
            self.assertIn("Shannon", rows[0].actor_label)

            clear_rotation(db, day, group.id, admin=admin)
            rows = recent_call_schedule_audit_logs(db, limit=10)
            self.assertEqual(len(rows), 2)
            self.assertEqual(rows[0].action, "clear")
            self.assertEqual(rows[0].from_surgeon_id, chris.id)
            self.assertIsNone(rows[0].to_surgeon_id)
        finally:
            db.close()

    def test_native_and_portal_cover_audit(self):
        db = self.Session()
        try:
            admin, chris, alex, group = self._seed(db)
            day = date.today() + timedelta(days=3)
            rotation = CallRotation(
                surgeon_id=chris.id,
                date=day,
                call_group_id=group.id,
                rotation_type="primary",
            )
            db.add(rotation)
            db.commit()
            db.refresh(rotation)

            with patch("app.native_call_coverage_service.send_native_push_to_surgeon"), \
                 patch("app.native_call_coverage_service.notify_admins"), \
                 patch("app.native_call_coverage_service._coverage_swap_warnings", return_value=[]):
                assign_native_call_coverage(db, chris, rotation.id, covering_surgeon_id=alex.id, notes="Swap WG")

            row = db.query(CallScheduleAuditLog).filter(CallScheduleAuditLog.source == "native").one()
            self.assertEqual(row.action, "cover")
            self.assertEqual(row.from_surgeon_id, chris.id)
            self.assertEqual(row.to_surgeon_id, alex.id)
            self.assertEqual(row.notes, "Swap WG")

            # Portal re-cover back — still audits
            with patch("app.native_call_coverage_service.send_native_push_to_surgeon"), \
                 patch("app.native_call_coverage_service._coverage_swap_warnings", return_value=[]):
                assign_admin_call_coverage(db, rotation.id, chris.id, notes="Portal restore", admin=admin)
            portal = (
                db.query(CallScheduleAuditLog)
                .filter(CallScheduleAuditLog.source == "portal", CallScheduleAuditLog.action == "cover")
                .order_by(CallScheduleAuditLog.id.desc())
                .first()
            )
            self.assertIsNotNone(portal)
            self.assertEqual(portal.to_surgeon_id, chris.id)
            self.assertEqual(portal.actor_admin_id, admin.id)
        finally:
            db.close()


if __name__ == "__main__":
    unittest.main()
