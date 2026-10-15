import os
import unittest
from datetime import date

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("SECRET_KEY", "test-secret")

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.call_assignment_normalization import effective_calls, sync_call_rotation
from app.models import (
    Base,
    CallCoverage,
    CallDailyAssignment,
    CallGroup,
    CallGroupLocation,
    CallRotation,
    Location,
    Surgeon,
)


class CallAssignmentNormalizationTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.db = sessionmaker(bind=self.engine)()

    def tearDown(self):
        self.db.close()
        Base.metadata.drop_all(self.engine)
        self.engine.dispose()

    def test_one_group_is_one_call_even_with_two_hospitals(self):
        original = Surgeon(first_name="One", last_name="Surgeon", email="one@example.com", is_active=True)
        covering = Surgeon(first_name="Two", last_name="Surgeon", email="two@example.com", is_active=True)
        first = Location(name="Winter Garden", abbreviation="WG", location_type="hospital")
        second = Location(name="Apopka", abbreviation="AP", location_type="hospital")
        group = CallGroup(name="Winter Garden")
        self.db.add_all([original, covering, first, second, group])
        self.db.flush()
        self.db.add_all([
            CallGroupLocation(call_group_id=group.id, location_id=first.id),
            CallGroupLocation(call_group_id=group.id, location_id=second.id),
        ])
        day = date(2026, 9, 23)
        rotation = CallRotation(date=day, call_group_id=group.id, surgeon_id=original.id)
        self.db.add(rotation)
        self.db.flush()

        rows = effective_calls(self.db, day, day)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].surgeon_id, original.id)
        self.assertIsNone(rows[0].call_coverage_id)
        self.assertEqual(rows[0].place, "WG, AP")

        coverage = CallCoverage(
            call_rotation_id=rotation.id,
            original_surgeon_id=original.id,
            covering_surgeon_id=covering.id,
            status="active",
        )
        self.db.add(coverage)
        self.db.flush()
        self.db.expire_all()

        rows = effective_calls(self.db, day, day)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].surgeon_id, covering.id)
        self.assertEqual(rows[0].call_coverage_id, coverage.id)
        self.assertEqual([location.id for location in rows[0].locations], [first.id, second.id])

        self.assertEqual(sync_call_rotation(self.db, rotation), 0)
        self.assertEqual(self.db.query(CallDailyAssignment).count(), 0)


if __name__ == "__main__":
    unittest.main()
