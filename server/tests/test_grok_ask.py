import os
import unittest
from datetime import date

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("SECRET_KEY", "test-secret")

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.grok_ask_service import ask_grok, parse_topic, parse_window
from app.models import Base, ClinicSchedule, DayOff, Location, Surgeon


class GrokAskWindowTest(unittest.TestCase):
    def test_last_month_is_previous_calendar_month(self):
        window = parse_window("How many days last month", date(2026, 8, 26))
        self.assertEqual(window["start"], date(2026, 7, 1))
        self.assertEqual(window["end"], date(2026, 7, 31))
        self.assertEqual(window["label"], "July 2026")

    def test_last_week_is_prior_monday_sunday(self):
        window = parse_window("clinic last week", date(2026, 8, 26))
        self.assertEqual(window["start"], date(2026, 8, 17))
        self.assertEqual(window["end"], date(2026, 8, 23))

    def test_taken_off_is_time_off(self):
        self.assertEqual(parse_topic("How many days has Alex Schroeder taken off last month?"), "time_off")

    def test_clinic_patients_is_clinic(self):
        self.assertEqual(
            parse_topic("How many patients did Chris Johnson see in clinic last week?"),
            "clinic",
        )

    def test_what_is_today_is_when(self):
        self.assertEqual(parse_topic("what is today"), "when")

    def test_this_month_to_date_is_first_through_today(self):
        window = parse_window(
            "how many clinical patient has Alex seen this month to date",
            date(2026, 8, 26),
        )
        self.assertEqual(window["start"], date(2026, 8, 1))
        self.assertEqual(window["end"], date(2026, 8, 26))
        self.assertEqual(window["label"], "August 2026 to date")

    def test_clinical_patient_is_clinic(self):
        self.assertEqual(
            parse_topic("how many clinical patient has Alex seen this month to date"),
            "clinic",
        )


class GrokAskLiveBoardTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(bind=self.engine)
        self.Session = sessionmaker(bind=self.engine)

    def tearDown(self):
        Base.metadata.drop_all(bind=self.engine)
        self.engine.dispose()

    def test_schroeder_time_off_last_month(self):
        db = self.Session()
        try:
            alex = Surgeon(
                first_name="Alex", last_name="Schroeder",
                email="as@example.com", is_active=True, staff_type="physician",
            )
            db.add(alex)
            db.flush()
            db.add(DayOff(
                surgeon_id=alex.id,
                start_date=date(2026, 7, 6),
                end_date=date(2026, 7, 8),
                status="approved",
                reason="Day Off",
            ))
            db.commit()
            result = ask_grok(
                db,
                "How many days has Alex Schroeder taken off last month?",
                today=date(2026, 8, 26),
            )
            self.assertTrue(result["ok"])
            self.assertEqual(result["topic"], "time_off")
            self.assertEqual(result["count"], 3)
            self.assertIn("3 approved time-off days", result["answer"])
            self.assertIn("July 2026", result["answer"])
            self.assertNotIn("PTO", result["answer"])
        finally:
            db.close()

    def test_johnson_clinic_patients_last_week(self):
        db = self.Session()
        try:
            chris = Surgeon(
                first_name="Chris", last_name="Johnson",
                email="cj@example.com", is_active=True, staff_type="physician",
            )
            loc = Location(name="Health Park", abbreviation="HP-CL", location_type="clinic", is_active=True)
            db.add_all([chris, loc])
            db.flush()
            db.add(ClinicSchedule(
                surgeon_id=chris.id,
                location_id=loc.id,
                date=date(2026, 8, 18),
                session="am",
                assignment_type="assigned",
                notes="Desk fax #9 · 09:00 SMITH, JANE; 09:15 DOE, JOHN; 09:30 LEE, PAT",
            ))
            db.commit()
            result = ask_grok(
                db,
                "How many patients did Chris Johnson see in clinic last week?",
                today=date(2026, 8, 26),
            )
            self.assertTrue(result["ok"])
            self.assertEqual(result["topic"], "clinic")
            self.assertEqual(result["count"], 3)
            self.assertIn("3 clinic patients", result["answer"])
        finally:
            db.close()

    def test_who_is_off_today(self):
        db = self.Session()
        try:
            alex = Surgeon(
                first_name="Alex", last_name="Schroeder",
                email="as@example.com", is_active=True, staff_type="physician",
            )
            db.add(alex)
            db.flush()
            db.add(DayOff(
                surgeon_id=alex.id,
                start_date=date(2026, 8, 26),
                end_date=date(2026, 8, 26),
                status="approved",
                reason="Day Off",
            ))
            db.commit()
            result = ask_grok(db, "Who is off today?", today=date(2026, 8, 26))
            self.assertEqual(result["topic"], "who_off")
            self.assertIn("Alex Schroeder", result["answer"])
        finally:
            db.close()

    def test_what_is_today(self):
        db = self.Session()
        try:
            result = ask_grok(db, "what is today", today=date(2026, 8, 26))
            self.assertEqual(result["topic"], "when")
            self.assertIn("Wednesday", result["answer"])
            self.assertIn("August 26, 2026", result["answer"])
        finally:
            db.close()

    def test_what_is_tomorrow(self):
        db = self.Session()
        try:
            result = ask_grok(db, "What is tomorrow?", today=date(2026, 8, 26))
            self.assertEqual(result["topic"], "when")
            self.assertIn("Thursday", result["answer"])
            self.assertIn("August 27, 2026", result["answer"])
        finally:
            db.close()

    def test_freeform_does_not_require_a_doctor(self):
        db = self.Session()
        try:
            result = ask_grok(db, "hello", today=date(2026, 8, 26))
            self.assertTrue(result["ok"])
            self.assertNotIn("could not tell who", result["answer"].lower())
            self.assertIn("Wednesday", result["answer"])
        finally:
            db.close()

    def test_alex_clinical_patients_this_month_to_date(self):
        db = self.Session()
        try:
            alex = Surgeon(
                first_name="Alex", last_name="Schroeder",
                email="as@example.com", is_active=True, staff_type="physician",
            )
            loc = Location(name="Health Park", abbreviation="HP-CL", location_type="clinic", is_active=True)
            db.add_all([alex, loc])
            db.flush()
            db.add(ClinicSchedule(
                surgeon_id=alex.id,
                location_id=loc.id,
                date=date(2026, 8, 4),
                session="am",
                assignment_type="assigned",
                notes="Desk fax · 09:00 SMITH, JANE; 09:15 DOE, JOHN",
            ))
            db.add(ClinicSchedule(
                surgeon_id=alex.id,
                location_id=loc.id,
                date=date(2026, 8, 18),
                session="am",
                assignment_type="assigned",
                notes="Desk fax · 09:00 LEE, PAT",
            ))
            db.add(ClinicSchedule(
                surgeon_id=alex.id,
                location_id=loc.id,
                date=date(2026, 7, 8),
                session="am",
                assignment_type="assigned",
                notes="Desk fax · 09:00 OLD, PATIENT",
            ))
            db.commit()
            result = ask_grok(
                db,
                "how many clinical patient has Alex seen this month to date",
                today=date(2026, 8, 26),
            )
            self.assertEqual(result["topic"], "clinic", result)
            self.assertEqual(result["count"], 3, result)
            self.assertIn("Alex Schroeder", result["answer"])
            self.assertIn("3 clinic patients", result["answer"])
            self.assertIn("to date", result["answer"])
            self.assertNotIn("could not tell who", result["answer"].lower())
        finally:
            db.close()
