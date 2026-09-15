"""Hard write guards for surgical cases."""

import os
import unittest
from datetime import date, time

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("SECRET_KEY", "test-secret")

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.admin_surgical_schedule_service import add_surgical_case
from app.models import Base, Location, ORBlockAssignment, ORBlockInstance, Surgeon, SurgicalCase


class SurgicalCaseWriteGuardrailsTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)
        self.db = self.Session()
        self.surgeon = Surgeon(
            first_name="Jorge",
            last_name="Florin",
            email="jf@example.com",
            is_active=True,
            staff_type="physician",
        )
        self.mn_or = Location(
            name="Minneola OR",
            abbreviation="MN-OR",
            location_type="hospital",
            color="#7CBFDE",
            is_active=True,
        )
        self.cbo = Location(
            name="CBO Clinic",
            abbreviation="CBO-OV",
            location_type="clinic",
            color="#DDF2FC",
            is_active=True,
        )
        self.db.add_all([self.surgeon, self.mn_or, self.cbo])
        self.db.commit()
        self.block = ORBlockInstance(
            location_id=self.mn_or.id,
            date=date(2026, 9, 16),
            session="am",
            start_time=time(7, 0),
            end_time=time(12, 0),
            status="assigned",
            room_text="MIN S05",
        )
        self.db.add(self.block)
        self.db.flush()
        self.db.add(ORBlockAssignment(
            block_instance_id=self.block.id,
            surgeon_id=self.surgeon.id,
            start_time=time(7, 15),
            case_count=1,
        ))
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def _fields(self, **overrides):
        fields = {
            "surgeon_id": self.surgeon.id,
            "date": date(2026, 9, 16),
            "start_time": time(7, 15),
            "end_time": None,
            "patient_name": "White, Jeffrey",
            "procedure": "Case",
            "location_id": self.mn_or.id,
            "room_text": "",
            "status": "scheduled",
            "notes": None,
        }
        fields.update(overrides)
        return fields

    def test_add_attaches_to_existing_static_block(self):
        case, _warn = add_surgical_case(self.db, self._fields(), notify=False)
        self.assertEqual(case.or_block_instance_id, self.block.id)
        self.assertEqual(case.location_id, self.mn_or.id)
        self.assertEqual(case.room_text, "MIN S05")

    def test_cbo_is_rejected_even_if_manually_entered(self):
        with self.assertRaisesRegex(ValueError, "Aprima only"):
            add_surgical_case(
                self.db,
                self._fields(location_id=self.cbo.id, room_text="CBO"),
                notify=False,
            )
        self.assertEqual(self.db.query(SurgicalCase).count(), 0)

    def test_case_without_matching_static_block_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "assigned static Block OR"):
            add_surgical_case(
                self.db,
                self._fields(start_time=time(13, 0)),
                notify=False,
            )
        self.assertEqual(self.db.query(SurgicalCase).count(), 0)

    def test_same_time_collision_is_rejected(self):
        add_surgical_case(self.db, self._fields(), notify=False)
        with self.assertRaisesRegex(ValueError, "already has a case"):
            add_surgical_case(
                self.db,
                self._fields(patient_name="Second, Patient"),
                notify=False,
            )
        self.assertEqual(self.db.query(SurgicalCase).count(), 1)


if __name__ == "__main__":
    unittest.main()
