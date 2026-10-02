import os
import unittest
from datetime import date, timedelta
from unittest.mock import patch

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("SECRET_KEY", "test-secret")

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.admin_call_schedule_action_service import assign_rotation
from app.call_backup_service import clear_backup, save_backup
from app.models import AdminUser, Base, CallBackup, CallCoverage, CallGroup, CallRotation, CallScheduleAuditLog, DayOff, Surgeon
from app.native_call_support import serialize_call_assignment
from app.native_home_sections import build_native_call_schedule


class CallBackupTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(bind=self.engine)
        self.db = sessionmaker(bind=self.engine)()
        self.admin = AdminUser(username="scheduler", email="scheduler@example.com", password_hash="x")
        self.primary = Surgeon(first_name="Jonathan", last_name="Dean", email="dean@example.com", is_active=True, staff_type="physician")
        self.backup = Surgeon(first_name="Alex", last_name="Florin", email="florin@example.com", is_active=True, staff_type="physician")
        self.other = Surgeon(first_name="Chris", last_name="Johnson", email="johnson@example.com", is_active=True, staff_type="physician")
        self.group = CallGroup(name="Altamonte", sort_order=1)
        self.db.add_all([self.admin, self.primary, self.backup, self.other, self.group])
        self.db.flush()
        self.rotation = CallRotation(date=date.today() + timedelta(days=2), call_group_id=self.group.id, surgeon_id=self.primary.id)
        self.db.add(self.rotation)
        self.db.commit()

    def tearDown(self):
        self.db.close()
        Base.metadata.drop_all(bind=self.engine)
        self.engine.dispose()

    @patch("app.call_backup_service.check_conflicts_structured", return_value=[])
    def test_optional_backup_and_note_do_not_replace_primary(self, _conflicts):
        before = serialize_call_assignment(self.rotation, self.primary.id)
        self.assertIsNone(before["backupSurgeon"])
        self.assertIsNone(self.db.query(CallBackup).first())

        save_backup(self.db, self.rotation.id, self.backup.id, "Call me if needed", admin=self.admin)
        after = serialize_call_assignment(self.rotation, self.primary.id)
        self.assertEqual(after["surgeonId"], self.primary.id)
        self.assertEqual(after["backupSurgeonId"], self.backup.id)
        self.assertEqual(after["backupNote"], "Call me if needed")
        self.assertFalse(after["isCovered"])
        day_key = self.rotation.date.isoformat()
        days = {day_key: {"callAssignments": [], "offSurgeons": [], "requestedOffSurgeons": []}}
        build_native_call_schedule(self.db, self.primary, self.rotation.date, self.rotation.date, days)
        self.assertEqual(days[day_key]["callAssignments"][0]["backupNote"], "Call me if needed")

        save_backup(self.db, self.rotation.id, self.other.id, "Updated by scheduler", admin=self.admin)
        self.assertEqual(self.db.query(CallBackup).count(), 1)
        self.assertEqual(serialize_call_assignment(self.rotation, self.primary.id)["backupSurgeonId"], self.other.id)
        self.assertEqual(self.db.query(CallScheduleAuditLog).filter_by(action="backup").count(), 2)

        clear_backup(self.db, self.rotation.id, admin=self.admin)
        self.assertIsNone(serialize_call_assignment(self.rotation, self.primary.id)["backupSurgeon"])
        self.assertEqual(self.db.query(CallBackup).count(), 0)
        self.assertEqual(self.db.query(CallScheduleAuditLog).filter_by(action="backup_clear").count(), 1)

    @patch("app.call_backup_service.check_conflicts_structured", return_value=[])
    def test_reassigning_primary_removes_old_backup(self, _conflicts):
        save_backup(self.db, self.rotation.id, self.backup.id, "Orientation", admin=self.admin)
        with patch("app.admin_call_schedule_action_service.send_push_to_surgeon"):
            assign_rotation(self.db, self.rotation.date, self.other.id, self.group.id, admin=self.admin)
        self.assertEqual(self.db.query(CallBackup).count(), 0)
        self.assertEqual(serialize_call_assignment(self.rotation, self.other.id)["surgeonId"], self.other.id)

    def test_primary_cannot_be_own_backup(self):
        with self.assertRaises(HTTPException):
            save_backup(self.db, self.rotation.id, self.primary.id, "", admin=self.admin)

    @patch("app.call_backup_service.check_conflicts_structured", return_value=[])
    def test_active_coverage_hides_backup_and_prevents_edit(self, _conflicts):
        save_backup(self.db, self.rotation.id, self.backup.id, "Available for Dean", admin=self.admin)
        self.db.add(CallCoverage(
            call_rotation_id=self.rotation.id, original_surgeon_id=self.primary.id,
            covering_surgeon_id=self.other.id, status="active",
        ))
        self.db.commit()
        assignment = serialize_call_assignment(self.rotation, self.primary.id)
        self.assertEqual(assignment["surgeonId"], self.other.id)
        self.assertIsNone(assignment["backupSurgeonId"])
        with self.assertRaises(HTTPException):
            save_backup(self.db, self.rotation.id, self.other.id, "", admin=self.admin)

    @patch("app.call_backup_service.check_conflicts_structured", return_value=[])
    def test_no_call_is_flagged_without_blocking_backup(self, _conflicts):
        self.db.add(DayOff(
            surgeon_id=self.backup.id, start_date=self.rotation.date, end_date=self.rotation.date,
            reason="No Call", status="approved",
        ))
        self.db.commit()
        warnings = save_backup(self.db, self.rotation.id, self.backup.id, "Scheduler approved exception", admin=self.admin)
        self.assertTrue(any("No Call" in warning for warning in warnings))
        self.assertEqual(serialize_call_assignment(self.rotation, self.primary.id)["backupSurgeonId"], self.backup.id)


if __name__ == "__main__":
    unittest.main()
