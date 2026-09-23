import os
import unittest
from datetime import date

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("SECRET_KEY", "test-secret")

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.call_assignment_normalization import sync_call_rotation
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

    def test_swap_replaces_effective_surgeon_per_location(self):
        original = Surgeon(first_name="One", last_name="Surgeon", email="one@example.com")
        covering = Surgeon(first_name="Two", last_name="Surgeon", email="two@example.com")
        location = Location(name="Winter Garden", abbreviation="WG-OR", location_type="hospital")
        group = CallGroup(name="Winter Garden")
        self.db.add_all([original, covering, location, group])
        self.db.flush()
        self.db.add(CallGroupLocation(call_group_id=group.id, location_id=location.id))
        rotation = CallRotation(date=date(2026, 9, 23), call_group_id=group.id, surgeon_id=original.id)
        self.db.add(rotation)
        self.db.flush()
        sync_call_rotation(self.db, rotation)
        self.assertEqual(self.db.query(CallDailyAssignment).one().surgeon_id, original.id)

        coverage = CallCoverage(
            call_rotation_id=rotation.id,
            original_surgeon_id=original.id,
            covering_surgeon_id=covering.id,
            status="active",
        )
        self.db.add(coverage)
        self.db.flush()
        sync_call_rotation(self.db, rotation)

        assignment = self.db.query(CallDailyAssignment).one()
        self.assertEqual(assignment.surgeon_id, covering.id)
        self.assertEqual(assignment.call_coverage_id, coverage.id)
        self.assertEqual(assignment.location_id, location.id)


if __name__ == "__main__":
    unittest.main()
