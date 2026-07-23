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
        self.assertNotEqual(resolve_or_location(self.db, "APK S03").id, self.hp_cl.id)
        self.assertEqual(resolve_clinic_location(self.db, "AHMGGENSRG").abbreviation, "HP-CL")

    def test_clinic_prefers_surgeon_schedule_over_fax_site(self):
        day = date(2026, 7, 27)
        self.db.add_all([
            ClinicSchedule(
                surgeon_id=self.surgeon.id,
                location_id=self.ap_or.id,
                date=day,
                session="am",
                assignment_type="assigned",
            ),
            ClinicSchedule(
                surgeon_id=self.surgeon.id,
                location_id=self.ap_cl.id,
                date=day,
                session="pm",
                assignment_type="assigned",
            ),
        ])
        self.db.commit()
        loc = resolve_clinic_location(
            self.db,
            "AHMGGENSRG",
            surgeon_id=self.surgeon.id,
            day=day,
            session="pm",
        )
        self.assertEqual(loc.abbreviation, "AP-CL")
        or_loc = resolve_or_location(
            self.db,
            None,
            surgeon_id=self.surgeon.id,
            day=day,
            session="am",
        )
        self.assertEqual(or_loc.abbreviation, "AP-OR")

    def test_block_window_requires_fax_times(self):
        start, end = _block_window_for_cases(
            [{"start_time": "08:30"}, {"start_time": "09:45"}],
            "am",
        )
        self.assertEqual(start, time(8, 30))
        self.assertEqual(end, time(11, 15))
        with self.assertRaises(ValueError):
            _block_window_for_cases([], "am")

    def test_ingest_creates_block_cases_and_clinic(self):
        day = date(2026, 7, 27)
        self.db.add_all([
            ClinicSchedule(
                surgeon_id=self.surgeon.id,
                location_id=self.ap_or.id,
                date=day,
                session="am",
                assignment_type="assigned",
            ),
            ClinicSchedule(
                surgeon_id=self.surgeon.id,
                location_id=self.ap_cl.id,
                date=day,
                session="pm",
                assignment_type="assigned",
            ),
        ])
        self.db.commit()

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
        self.assertEqual(result["blocks"][0]["action"], "created")
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
        clinic = self.db.query(ClinicSchedule).filter(ClinicSchedule.session == "pm").one()
        self.assertEqual(clinic.location_id, self.ap_cl.id)
        self.assertIn("13:00", clinic.notes or "")

    def test_ingest_expands_existing_block(self):
        day = date(2026, 7, 27)
        existing = ORBlockInstance(
            series_id=None,
            location_id=self.ap_or.id,
            date=day,
            session="am",
            start_time=time(7, 0),
            end_time=time(10, 0),
            status="open",
            notes="seeded months out",
        )
        self.db.add(existing)
        self.db.commit()

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
                                "start_time": "09:00",
                                "patient_name": "Late Case, Pt",
                                "procedure": "Hernia",
                                "room": "APK S03",
                            },
                            {
                                "case_date": "2026-07-27",
                                "start_time": "10:30",
                                "patient_name": "Later Case, Pt",
                                "procedure": "Chole",
                                "room": "APK S03",
                            },
                        ],
                    },
                }
            ],
        )
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["blocks"][0]["action"], "expanded")
        self.assertEqual(self.db.query(ORBlockInstance).count(), 1)
        block = self.db.query(ORBlockInstance).one()
        self.assertEqual(block.start_time, time(7, 0))
        self.assertEqual(block.end_time, time(12, 0))  # 10:30 + 90m
        self.assertEqual(self.db.query(ORBlockAssignment).count(), 1)

    def _florin_payload(self, cases, *, start="2026-07-27", end="2026-07-27", clinic=False):
        block = {
            "surgeon_name": "Jorge Luis Florin, MD",
            "start_date": start,
            "end_date": end,
            "or_block": {
                "session": "am",
                "room": "APK S03",
                "cases": cases,
            },
        }
        if clinic:
            block["clinic_rotation"] = {
                "session": "pm",
                "site_raw": "AHMGGENSRG",
                "slots": [
                    {
                        "case_date": start,
                        "start_time": "13:00",
                        "patient_name": "Clinic Pt",
                        "site_raw": "AHMGGENSRG",
                    }
                ],
            }
        return [block]

    def test_reingest_identical_is_ignored(self):
        day = "2026-07-27"
        cases = [
            {
                "case_date": day,
                "start_time": "08:30",
                "patient_name": "Sheffield, Martin",
                "procedure": "Hernia",
                "room": "APK S03",
            }
        ]
        first = ingest_surgeon_schedule(self.db, source_fax_id=3, surgeons=self._florin_payload(cases))
        self.assertEqual(first["cases_created"], 1)
        second = ingest_surgeon_schedule(self.db, source_fax_id=26, surgeons=self._florin_payload(cases))
        self.assertEqual(second["cases_created"], 0)
        self.assertEqual(second["cases_unchanged"], 1)
        self.assertEqual(second["cases_updated"], 0)
        self.assertEqual(self.db.query(SurgicalCase).filter(SurgicalCase.status != "cancelled").count(), 1)
        row = self.db.query(SurgicalCase).one()
        self.assertIn("Desk fax #3", row.notes or "")

    def test_reingest_time_or_room_change_updates(self):
        day = "2026-07-27"
        first_cases = [
            {
                "case_date": day,
                "start_time": "08:30",
                "patient_name": "Sheffield, Martin",
                "procedure": "Hernia",
                "room": "APK S03",
            }
        ]
        ingest_surgeon_schedule(self.db, source_fax_id=3, surgeons=self._florin_payload(first_cases))
        changed = [
            {
                "case_date": day,
                "start_time": "09:00",
                "patient_name": "Sheffield",
                "procedure": "Hernia",
                "room": "APK S05",
            }
        ]
        result = ingest_surgeon_schedule(self.db, source_fax_id=26, surgeons=self._florin_payload(changed))
        self.assertEqual(result["cases_updated"], 1)
        self.assertEqual(self.db.query(SurgicalCase).filter(SurgicalCase.status != "cancelled").count(), 1)
        row = self.db.query(SurgicalCase).one()
        self.assertEqual(row.start_time, time(9, 0))
        self.assertEqual(row.room_text, "APK S05")
        self.assertEqual(row.patient_name, "Sheffield, Martin")

    def test_reingest_removes_missing_desk_case(self):
        day = "2026-07-27"
        first_cases = [
            {
                "case_date": day,
                "start_time": "08:30",
                "patient_name": "Sheffield, Martin",
                "procedure": "Hernia",
                "room": "APK S03",
            },
            {
                "case_date": day,
                "start_time": "09:45",
                "patient_name": "Cruz Mejia, Cristina",
                "procedure": "Chole",
                "room": "APK S03",
            },
        ]
        ingest_surgeon_schedule(self.db, source_fax_id=3, surgeons=self._florin_payload(first_cases))
        only_sheffield = [first_cases[0]]
        result = ingest_surgeon_schedule(
            self.db, source_fax_id=26, surgeons=self._florin_payload(only_sheffield)
        )
        self.assertEqual(result["cases_removed"], 1)
        active = self.db.query(SurgicalCase).filter(SurgicalCase.status != "cancelled").all()
        self.assertEqual(len(active), 1)
        self.assertIn("Sheffield", active[0].patient_name)
        cancelled = self.db.query(SurgicalCase).filter(SurgicalCase.status == "cancelled").one()
        self.assertIn("Cruz", cancelled.patient_name)

    def test_fax_duplicate_lines_do_not_create_second_row(self):
        day = "2026-07-27"
        cases = [
            {
                "case_date": day,
                "start_time": "08:30",
                "patient_name": "Sheffield, Martin",
                "procedure": "Hernia",
                "room": "APK S03",
            },
            {
                "case_date": day,
                "start_time": "08:30",
                "patient_name": "Sheffield",
                "procedure": "Hernia",
                "room": "APK S03",
            },
        ]
        result = ingest_surgeon_schedule(self.db, source_fax_id=26, surgeons=self._florin_payload(cases))
        self.assertEqual(result["cases_created"], 1)
        self.assertEqual(result["cases_unchanged"], 1)
        self.assertEqual(self.db.query(SurgicalCase).count(), 1)


if __name__ == "__main__":
    unittest.main()
