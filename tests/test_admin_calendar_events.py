import os
import unittest
from datetime import date

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("SECRET_KEY", "test-secret")

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api_calendar_admin_event_serializers import call_rotation_event
from app.api_calendar_utils import call_group_abbrev
from app.models import Base, CallCoverage, CallGroup, CallRotation, Surgeon


class AdminCalendarEventsTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(bind=self.engine)
        self.Session = sessionmaker(bind=self.engine)

    def tearDown(self):
        Base.metadata.drop_all(bind=self.engine)
        self.engine.dispose()

    def test_call_group_abbrev_matches_master_calendar_labels(self):
        self.assertEqual(call_group_abbrev("Winter Garden / Apopka / Minneola Hospital"), "WG")
        self.assertEqual(call_group_abbrev("Altamonte Hospital"), "AL")

    def test_call_rotation_event_uses_active_covering_surgeon(self):
        db = self.Session()
        try:
            original = Surgeon(first_name="Alexander", last_name="Schroeder", is_active=True)
            covering = Surgeon(first_name="Lucy", last_name="Woodley", is_active=True)
            group = CallGroup(name="Winter Garden / Apopka / Minneola Hospital")
            db.add_all([original, covering, group])
            db.commit()

            rotation = CallRotation(
                date=date(2026, 7, 24),
                surgeon_id=original.id,
                call_group_id=group.id,
            )
            db.add(rotation)
            db.commit()

            coverage = CallCoverage(
                call_rotation_id=rotation.id,
                original_surgeon_id=original.id,
                covering_surgeon_id=covering.id,
                status="active",
            )
            db.add(coverage)
            db.commit()
            db.refresh(rotation)

            event = call_rotation_event(rotation)
            props = event["extendedProps"]

            self.assertEqual(event["title"], "WG: LW")
            self.assertEqual(props["surgeon_id"], covering.id)
            self.assertEqual(props["surgeon"], "Lucy Woodley")
            self.assertEqual(props["original_surgeon_id"], original.id)
            self.assertEqual(props["original_initials"], "AS")
            self.assertEqual(props["covering_surgeon_id"], covering.id)
            self.assertEqual(props["covering_initials"], "LW")
            self.assertTrue(props["is_covered"])
        finally:
            db.close()


if __name__ == "__main__":
    unittest.main()
