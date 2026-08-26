import os
import unittest
from datetime import date, time

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("SECRET_KEY", "test-secret")

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.grok_ask_service import ask_grok, parse_topic, parse_window
from app.models import Base, CallGroup, CallRotation, ClinicSchedule, DayOff, Location, Meeting, Surgeon

# Practice English → topic. When Ask misses, add the phrase here first.
QUESTION_CATALOG = (
    ("Who has coverage today", "who_call"),
    ("today's coverage", "who_call"),
    ("Todays Coverage", "who_call"),
    ("who is covering today", "who_call"),
    ("who is on call today", "who_call"),
    ("Call Schedule", "who_call"),
    ("who is off today", "who_off"),
    ("who is out today", "who_off"),
    ("Out Today", "who_off"),
    ("who has no call today", "no_call"),
    ("No Call Today", "no_call"),
    ("who is in clinic today", "who_clinic"),
    ("Clinic Visits Today", "clinic_visits"),
    ("Surgical Cases Today", "cases"),
    ("Available Today", "available"),
    ("Pending Approvals", "pending_off"),
    ("Meetings This Week", "meetings"),
    ("Upcoming Meetings", "meetings"),
    ("Admin Notifications", "notices"),
    ("Time Off", "time_off"),
    ("Block OR", "blocks"),
    ("Clinics / OR", "clinics_or"),
    ("Master Calendar", "board"),
    ("Physicians", "roster"),
    ("what meeting are scheduled this month", "meetings"),
    ("what's on the board today", "board"),
    ("who is working today", "board"),
    ("what is today", "when"),
    ("how many clinical patient has Alex seen this month to date", "clinic"),
    ("How many patients to be seen on Friday at the clermont office", "clinic"),
)


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

    def test_meetings_this_month_is_meetings_topic(self):
        self.assertEqual(parse_topic("what meeting are scheduled this month"), "meetings")

    def test_this_month_is_the_full_calendar_month(self):
        window = parse_window("what meeting are scheduled this month", date(2026, 8, 26))
        self.assertEqual(window["start"], date(2026, 8, 1))
        self.assertEqual(window["end"], date(2026, 8, 31))
        self.assertEqual(window["label"], "August 2026")

    def test_question_catalog_maps_practice_english(self):
        for question, topic in QUESTION_CATALOG:
            with self.subTest(question=question):
                self.assertEqual(parse_topic(question), topic, question)

    def test_meetings_this_week_is_rolling_seven_days(self):
        window = parse_window("Meetings This Week", date(2026, 8, 26))
        self.assertEqual(window["start"], date(2026, 8, 26))
        self.assertEqual(window["end"], date(2026, 9, 2))
        self.assertEqual(window["label"], "this week")

    def test_named_weekdays_are_the_matching_day_not_the_whole_week(self):
        today = date(2026, 8, 26)  # Wednesday
        expected = {
            "Monday": date(2026, 8, 31),
            "Tuesday": date(2026, 9, 1),
            "Wednesday": date(2026, 8, 26),
            "Thursday": date(2026, 8, 27),
            "Friday": date(2026, 8, 28),
            "Saturday": date(2026, 8, 29),
            "Sunday": date(2026, 8, 30),
        }
        for name, day in expected.items():
            with self.subTest(day=name):
                window = parse_window(
                    f"How many patients to be seen on {name} at the clermont office",
                    today,
                )
                self.assertEqual(window["start"], day, name)
                self.assertEqual(window["end"], day, name)
                self.assertIn(name, window["label"])


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

    def test_meetings_this_month_lists_board_rows(self):
        db = self.Session()
        try:
            loc = Location(
                name="Health Park", abbreviation="HP", location_type="hospital", is_active=True,
            )
            db.add(loc)
            db.flush()
            db.add(Meeting(
                title="Tumor Board",
                date=date(2026, 8, 28),
                start_time=time(7, 0),
                location_id=loc.id,
            ))
            db.add(Meeting(
                title="Friday huddle",
                date=date(2026, 8, 7),
                start_time=time(8, 30),
                location_text="Admin conference",
            ))
            db.commit()
            result = ask_grok(
                db,
                "what meeting are scheduled this month",
                today=date(2026, 8, 26),
            )
            self.assertTrue(result["ok"], result)
            self.assertEqual(result["topic"], "meetings", result)
            self.assertEqual(result["count"], 2, result)
            self.assertIn("Tumor Board", result["answer"])
            self.assertIn("Friday huddle", result["answer"])
            self.assertIn("August 2026", result["answer"])
            self.assertNotIn("I stay inside CAL", result["answer"])
            self.assertNotIn("could not tell who", result["answer"].lower())
        finally:
            db.close()

    def test_who_has_coverage_today_lists_call(self):
        db = self.Session()
        try:
            chris = Surgeon(
                first_name="Chris", last_name="Johnson",
                email="cj@example.com", is_active=True, staff_type="physician",
            )
            group = CallGroup(name="Winter Garden")
            db.add_all([chris, group])
            db.flush()
            db.add(CallRotation(
                surgeon_id=chris.id,
                call_group_id=group.id,
                date=date(2026, 8, 26),
            ))
            db.commit()
            result = ask_grok(db, "Who has coverage today", today=date(2026, 8, 26))
            self.assertTrue(result["ok"], result)
            self.assertEqual(result["topic"], "who_call", result)
            self.assertIn("Today's Coverage", result["answer"])
            self.assertIn("Chris Johnson", result["answer"])
            self.assertIn("Winter Garden", result["answer"])
            self.assertEqual(result["title"], "Today's Coverage")
            self.assertTrue(result["lines"])
            self.assertIn("Chris Johnson", result["lines"][0])
            self.assertTrue(result["answer"].startswith("Today's Coverage"))
            self.assertIn("• ", result["answer"])
            self.assertNotIn("don't have that", result["answer"].lower())
            self.assertNotIn("I stay inside CAL", result["answer"])
        finally:
            db.close()

    def test_clinic_visits_today_uses_dashboard_count(self):
        db = self.Session()
        try:
            chris = Surgeon(
                first_name="Chris", last_name="Johnson",
                email="cj@example.com", is_active=True, staff_type="physician",
            )
            loc = Location(
                name="Health Park", abbreviation="HP-CL", location_type="clinic", is_active=True,
            )
            db.add_all([chris, loc])
            db.flush()
            db.add(ClinicSchedule(
                surgeon_id=chris.id,
                location_id=loc.id,
                date=date(2026, 8, 26),
                session="am",
                assignment_type="assigned",
                notes="Desk fax · 09:00 SMITH, JANE; 09:15 DOE, JOHN",
            ))
            db.commit()
            result = ask_grok(db, "Clinic Visits Today", today=date(2026, 8, 26))
            self.assertEqual(result["topic"], "clinic_visits", result)
            self.assertEqual(result["count"], 2, result)
            self.assertIn("Clinic Visits Today", result["answer"])
            self.assertIn("2", result["answer"])
        finally:
            db.close()

    def test_available_today_matches_dashboard_card(self):
        db = self.Session()
        try:
            alex = Surgeon(
                first_name="Alex", last_name="Schroeder",
                email="as@example.com", is_active=True, staff_type="physician",
            )
            chris = Surgeon(
                first_name="Chris", last_name="Johnson",
                email="cj@example.com", is_active=True, staff_type="physician",
            )
            db.add_all([alex, chris])
            db.flush()
            db.add(DayOff(
                surgeon_id=alex.id,
                start_date=date(2026, 8, 26),
                end_date=date(2026, 8, 26),
                status="approved",
                reason="Day Off",
            ))
            db.commit()
            result = ask_grok(db, "Available Today", today=date(2026, 8, 26))
            self.assertEqual(result["topic"], "available", result)
            self.assertEqual(result["count"], 1, result)
            self.assertIn("Available Today", result["answer"])
            self.assertIn("1 / 2", result["answer"])
            self.assertIn("Alex Schroeder", result["answer"])
        finally:
            db.close()

    def test_patients_on_a_weekday_at_an_office_are_that_office_day(self):
        db = self.Session()
        try:
            chris = Surgeon(
                first_name="Chris", last_name="Johnson",
                email="cj@example.com", is_active=True, staff_type="physician",
            )
            clermont = Location(
                name="Clermont Office", abbreviation="CL-OF",
                location_type="clinic", is_active=True, city="Clermont",
            )
            winter = Location(
                name="Winter Garden OR", abbreviation="WG-OR",
                location_type="hospital", is_active=True,
            )
            db.add_all([chris, clermont, winter])
            db.flush()
            db.add(ClinicSchedule(
                surgeon_id=chris.id,
                location_id=clermont.id,
                date=date(2026, 8, 28),
                session="am",
                assignment_type="assigned",
                notes="Desk fax · 09:00 SMITH, JANE; 09:15 DOE, JOHN",
            ))
            db.add(ClinicSchedule(
                surgeon_id=chris.id,
                location_id=clermont.id,
                date=date(2026, 8, 27),
                session="am",
                assignment_type="assigned",
                notes="Desk fax · 09:00 LEE, PAT",
            ))
            db.add(ClinicSchedule(
                surgeon_id=chris.id,
                location_id=winter.id,
                date=date(2026, 8, 28),
                session="am",
                assignment_type="assigned",
                notes="Desk fax · 07:00 OR, CASE",
            ))
            db.commit()
            friday = ask_grok(
                db,
                "How many patients to be seen on Friday at the clermont office",
                today=date(2026, 8, 26),
            )
            self.assertEqual(friday["topic"], "clinic", friday)
            self.assertEqual(friday["count"], 2, friday)
            self.assertIn("Clermont Office", friday["answer"])
            self.assertIn("Friday", friday["answer"])
            self.assertIn("2 patient", friday["answer"])
            self.assertNotIn("Winter Garden", friday["answer"])
            self.assertNotIn("this week", friday["answer"].lower())

            thursday = ask_grok(
                db,
                "How many patients to be seen on Thursday at Clermont",
                today=date(2026, 8, 26),
            )
            self.assertEqual(thursday["count"], 1, thursday)
            self.assertIn("Thursday", thursday["answer"])
            self.assertIn("1 patient", thursday["answer"])
        finally:
            db.close()
