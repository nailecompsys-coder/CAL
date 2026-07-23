"""Tests for Desk → CAL surgeon-schedule ingest."""
import os
import unittest
from datetime import date, time

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("SECRET_KEY", "test-secret")

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.ingest_resolve import resolve_clinic_location, resolve_or_location, resolve_surgeon
from app.ingest_schedule_service import _block_window_for_cases, ingest_surgeon_schedule
from app.models import Base, ClinicSchedule, Location, ORBlockAssignment, ORBlockInstance, Surgeon, SurgicalCase


class IngestScheduleTest(unittest.TestCase):
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
        self.ap_or = Location(name="Apopka OR", abbreviation="AP-OR", location_type="hospital", color="#7CBFDE", is_active=True)
        self.ap_cl = Location(name="Apopka Clinic", abbreviation="AP-CL", location_type="clinic", color="#DDF2FC", is_active=True)
        self.hp_cl = Location(name="Health Park", abbreviation="HP-CL", location_type="clinic", color="#DDF2FC", is_active=True)
        self.db.add_all([self.surgeon, self.ap_or, self.ap_cl, self.hp_cl])
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def test_resolve_advent_names_and_rooms(self):
        self.assertEqual(resolve_surgeon(self.db, "Jorge Luis Florin, MD").id, self.surgeon.id)
        self.assertEqual(resolve_or_location(self.db, "APK S03").abbreviation, "AP-OR")
        self.assertEqual(resolve_clinic_location(self.db, "AHMGGENSRG").abbreviation, "HP-CL")

    def test_block_window_from_case_times(self):
        start, end = _block_window_for_cases(
            [{"start_time": "08:30"}, {"start_time": "09:45"}],
            "am",
        )
        self.assertEqual(start, time(8, 30))
        self.assertEqual(end, time(11, 15))

    def test_ingest_creates_block_cases_and_clinic(self):
        result = ingest_surgeon_schedule(
            self.db,
            source_fax_id=3,
            surgeons=[
                {
                    "surgeon_name": "Jorge Luis Florin, MD",
                    "start_date": "2026-07-27",
                    "or_block": {
                        "session": "am",
                        "room": "APK S03",
                        "cases": [
                            {
                                "case_date": "2026-07-27",
                                "start_time": "08:30",
                                "patient_name": "Sheffield, Martin",
                                "procedure": "Hernia",
                                "room": "APK S03",
                            },
                            {
                                "case_date": "2026-07-27",
                                "start_time": "09:45",
                                "patient_name": "Cruz Mejia, Cristina",
                                "procedure": "Chole",
                                "room": "APK S03",
                            },
                        ],
                    },
                    "clinic_rotation": {
                        "session": "pm",
                        "site_raw": "AHMGGENSRG",
                        "slots": [
                            {
                                "case_date": "2026-07-27",
                                "start_time": "13:00",
                                "patient_name": "Clinic Pt",
                                "site_raw": "AHMGGENSRG",
                            }
                        ],
                    },
                }
            ],
        )
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["blocks_count"], 1)
        self.assertEqual(result["cases_count"], 2)
        self.assertEqual(result["clinics_count"], 1)

        block = self.db.query(ORBlockInstance).one()
        self.assertEqual(block.location_id, self.ap_or.id)
        self.assertEqual(block.start_time, time(8, 30))
        self.assertEqual(self.db.query(ORBlockAssignment).count(), 1)
        cases = self.db.query(SurgicalCase).order_by(SurgicalCase.start_time).all()
        self.assertEqual(len(cases), 2)
        self.assertEqual(cases[0].location_id, self.ap_or.id)
        self.assertEqual(cases[0].or_block_instance_id, block.id)
        clinic = self.db.query(ClinicSchedule).one()
        self.assertEqual(clinic.location_id, self.hp_cl.id)
        self.assertEqual(clinic.session, "pm")
        self.assertIn("13:00", clinic.notes or "")


if __name__ == "__main__":
    unittest.main()
