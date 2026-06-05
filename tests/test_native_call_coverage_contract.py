import os
import unittest
from datetime import date
from unittest.mock import patch

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("SECRET_KEY", "test-secret")

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models import Base, CallCoverage, CallGroup, CallRotation, Surgeon
from app.native_support import serialize_call_assignment
from app.routers.api import NativeCallCoverageBody, native_call_coverage, native_cancel_call_coverage


class NativeCallCoverageContractTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(bind=self.engine)
        self.Session = sessionmaker(bind=self.engine)

    def tearDown(self):
        Base.metadata.drop_all(bind=self.engine)
        self.engine.dispose()

    def test_call_coverage_replaces_active_assignment_and_keeps_original_visible(self):
        db = self.Session()
        try:
            original, first_cover, second_cover, group, rotation = self._seed_rotation(db)

            with patch("app.routers.api.send_native_push_to_surgeon"):
                first_response = native_call_coverage(
                    NativeCallCoverageBody(rotation_id=rotation.id, covering_surgeon_id=first_cover.id, notes="Swap one"),
                    db=db,
                    auth=(original, "token"),
                )

            first_assignment = first_response["assignment"]
            self.assertTrue(first_response["ok"])
            self.assertTrue(first_assignment["isCovered"])
            self.assertEqual(first_assignment["originalInitials"], "CJ")
            self.assertEqual(first_assignment["coveringInitials"], "AS")
            self.assertEqual(first_assignment["initials"], "AS")
            self.assertEqual(first_assignment["surgeonId"], first_cover.id)
            first_coverage_id = first_assignment["coverageId"]

            with patch("app.routers.api.send_native_push_to_surgeon"):
                second_response = native_call_coverage(
                    NativeCallCoverageBody(rotation_id=rotation.id, covering_surgeon_id=second_cover.id, notes="Swap two"),
                    db=db,
                    auth=(original, "token"),
                )

            second_assignment = second_response["assignment"]
            self.assertTrue(second_response["ok"])
            self.assertTrue(second_assignment["isCovered"])
            self.assertEqual(second_assignment["originalSurgeonId"], original.id)
            self.assertEqual(second_assignment["originalInitials"], "CJ")
            self.assertEqual(second_assignment["coveringSurgeonId"], second_cover.id)
            self.assertEqual(second_assignment["coveringInitials"], "LW")
            self.assertEqual(second_assignment["initials"], "LW")
            self.assertEqual(second_assignment["surgeon"], second_cover.full_name)
            self.assertNotEqual(second_assignment["coverageId"], first_coverage_id)

            old_coverage = db.get(CallCoverage, first_coverage_id)
            self.assertEqual(old_coverage.status, "canceled")
            self.assertIsNotNone(old_coverage.canceled_at)

            active_coverages = (
                db.query(CallCoverage)
                .filter(CallCoverage.call_rotation_id == rotation.id, CallCoverage.status == "active")
                .all()
            )
            self.assertEqual(len(active_coverages), 1)
            self.assertEqual(active_coverages[0].covering_surgeon_id, second_cover.id)
        finally:
            db.close()

    def test_cancel_call_coverage_restores_original_assignment_shape(self):
        db = self.Session()
        try:
            original, cover, _, _, rotation = self._seed_rotation(db)
            coverage = CallCoverage(
                call_rotation_id=rotation.id,
                original_surgeon_id=original.id,
                covering_surgeon_id=cover.id,
                requested_by_surgeon_id=original.id,
                status="active",
            )
            db.add(coverage)
            db.commit()
            db.refresh(coverage)

            before_cancel = serialize_call_assignment(rotation, original.id)
            self.assertTrue(before_cancel["isCovered"])
            self.assertEqual(before_cancel["originalInitials"], "CJ")
            self.assertEqual(before_cancel["coveringInitials"], "AS")

            response = native_cancel_call_coverage(coverage.id, db=db, auth=(original, "token"))

            assignment = response["assignment"]
            self.assertTrue(response["ok"])
            self.assertFalse(assignment["isCovered"])
            self.assertIsNone(assignment["coverageId"])
            self.assertEqual(assignment["initials"], "CJ")
            self.assertEqual(assignment["surgeonId"], original.id)
            self.assertEqual(assignment["originalInitials"], "CJ")
            self.assertIsNone(assignment["coveringInitials"])

            canceled = db.get(CallCoverage, coverage.id)
            self.assertEqual(canceled.status, "canceled")
            self.assertIsNotNone(canceled.canceled_at)
        finally:
            db.close()

    def test_call_coverage_rejects_wrong_staff_type(self):
        db = self.Session()
        try:
            original, _, _, _, rotation = self._seed_rotation(db)
            staff = Surgeon(
                first_name="Pat",
                last_name="Staff",
                email="staff@example.com",
                staff_type="staff",
                sort_order=4,
                is_active=True,
            )
            db.add(staff)
            db.commit()
            db.refresh(staff)

            with self.assertRaises(HTTPException) as ctx:
                native_call_coverage(
                    NativeCallCoverageBody(rotation_id=rotation.id, covering_surgeon_id=staff.id),
                    db=db,
                    auth=(original, "token"),
                )

            self.assertEqual(ctx.exception.status_code, 400)
            self.assertIn("Coverage must be assigned", ctx.exception.detail)
        finally:
            db.close()

    def _seed_rotation(self, db):
        original = Surgeon(
            first_name="Chris",
            last_name="Johnson",
            email="chris@example.com",
            staff_type="physician",
            sort_order=1,
            is_active=True,
        )
        first_cover = Surgeon(
            first_name="Alex",
            last_name="Smith",
            email="alex@example.com",
            staff_type="physician",
            sort_order=2,
            is_active=True,
        )
        second_cover = Surgeon(
            first_name="Lauren",
            last_name="Winter",
            email="lauren@example.com",
            staff_type="physician",
            sort_order=3,
            is_active=True,
        )
        group = CallGroup(name="Winter Garden", sort_order=1)
        db.add_all([original, first_cover, second_cover, group])
        db.flush()

        rotation = CallRotation(
            call_group_id=group.id,
            surgeon_id=original.id,
            date=date(2026, 6, 15),
        )
        db.add(rotation)
        db.commit()
        db.refresh(original)
        db.refresh(first_cover)
        db.refresh(second_cover)
        db.refresh(group)
        db.refresh(rotation)
        return original, first_cover, second_cover, group, rotation


if __name__ == "__main__":
    unittest.main()
