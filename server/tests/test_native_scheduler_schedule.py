"""Scheduler uses saved card/source facts, including facts absent from Block OR."""

import os
import unittest
from datetime import date, time

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("SECRET_KEY", "test-secret")

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from fastapi.testclient import TestClient

from app.main import app
from app.models import (
    Base, ClinicSchedule, DayOff, Location, ScheduleCard, ScheduleCardActivity,
    ScheduleCardWeek, Surgeon, SurgicalCase,
)
from app.native_scheduler_schedule import scheduler_schedule


class NativeSchedulerScheduleTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(bind=self.engine)
        self.db = sessionmaker(bind=self.engine)()

    def tearDown(self):
        self.db.close()
        Base.metadata.drop_all(bind=self.engine)
        self.engine.dispose()

    def test_all_surgeons_get_master_cards_cases_clinic_and_approved_leave(self):
        monday = date(2026, 10, 5)
        primary = Surgeon(first_name="Chris", last_name="Johnson", sort_order=2, is_active=True)
        assistant = Surgeon(first_name="Alex", last_name="Smith", sort_order=1, is_active=True)
        staff = Surgeon(first_name="Casey", last_name="Staff", staff_type="staff", is_active=True)
        hospital = Location(name="Altamonte OR", abbreviation="AL-OR", location_type="hospital")
        clinic = Location(name="Lake Mary Clinic", abbreviation="LM", location_type="clinic")
        self.db.add_all([primary, assistant, staff, hospital, clinic])
        self.db.flush()
        week = ScheduleCardWeek(surgeon_id=primary.id, week_start=monday)
        self.db.add(week)
        self.db.flush()
        am = ScheduleCard(
            week_id=week.id, surgeon_id=primary.id, date=monday, session="am",
            baseline_state="assigned", effective_state="assigned",
            baseline_location_id=hospital.id, effective_location_id=hospital.id,
        )
        pm = ScheduleCard(
            week_id=week.id, surgeon_id=primary.id, date=monday, session="pm",
            baseline_state="na", effective_state="assigned", effective_location_id=clinic.id,
        )
        assistant_week = ScheduleCardWeek(surgeon_id=assistant.id, week_start=monday)
        self.db.add(assistant_week)
        self.db.flush()
        assistant_off = ScheduleCard(
            week_id=assistant_week.id, surgeon_id=assistant.id, date=monday, session="am",
            baseline_state="off", effective_state="off",
        )
        self.db.add_all([am, pm, assistant_off])
        self.db.flush()
        self.db.add_all([
            SurgicalCase(
                surgeon_id=primary.id, assisting_surgeon_id=assistant.id, date=monday,
                start_time=time(9), end_time=time(10), patient_name="Case Patient",
                procedure="Procedure", location_id=hospital.id, schedule_card_id=am.id,
                status="scheduled", or_block_instance_id=None,
            ),
            ScheduleCardActivity(
                schedule_card_id=pm.id, surgeon_id=primary.id, location_id=clinic.id,
                activity_date=monday, session="pm", activity_type="clinic",
                start_time=time(13), end_time=time(13, 30), patient_name="Visit Patient",
                procedure="Visit", source_system="fax_clinic", source_record_key="fax-visit-1",
                identity_key="visit-patient-1300", is_active=True,
            ),
            DayOff(surgeon_id=primary.id, start_date=monday, end_date=monday,
                   reason="Vacation", status="approved", is_full_day=False,
                   start_time=time(8), end_time=time(12)),
            DayOff(surgeon_id=assistant.id, start_date=monday, end_date=monday,
                   reason="No Call", status="approved", is_full_day=True),
            ClinicSchedule(surgeon_id=assistant.id, location_id=clinic.id, date=monday,
                           session="pm", assignment_type="assigned"),
        ])
        self.db.commit()

        rows = scheduler_schedule(self.db, monday, monday)
        self.assertNotIn(staff.id, {row["surgeonId"] for row in rows})
        self.assertEqual(assistant.id, rows[0]["surgeonId"])
        primary_rows = [row for row in rows if row["surgeonId"] == primary.id]
        assistant_rows = [row for row in rows if row["surgeonId"] == assistant.id]
        self.assertEqual(["AL-OR", "NA"], [row["title"] for row in primary_rows if row["type"] == "card"])
        self.assertTrue(any(row["type"] == "surgery" and row["needsReview"] for row in primary_rows))
        self.assertTrue(any(row["type"] == "clinic_visit" for row in primary_rows))
        self.assertTrue(any(row["type"] == "approved_off" and row["start"] == "08:00" for row in primary_rows))
        self.assertTrue(any(row["type"] == "surgery" and row["subtitle"].startswith("Assisting") for row in assistant_rows))
        self.assertTrue(any(row["type"] == "card" and row["title"] == "OFF" for row in assistant_rows))
        self.assertTrue(any(row["type"] == "surgery" and row["needsReview"] for row in assistant_rows))
        self.assertTrue(any(row["type"] == "no_call" for row in assistant_rows))
        self.assertTrue(any(row["type"] == "clinic_block" for row in assistant_rows))
        self.assertEqual(1, rows[0]["dayCaseCount"])
        self.assertEqual(1, rows[0]["dayVisitCount"])
        self.assertEqual(1, rows[0]["dayOffCount"])

    def test_weekend_has_no_master_cards_but_keeps_approved_leave(self):
        saturday = date(2026, 10, 10)
        surgeon = Surgeon(first_name="Chris", last_name="Johnson", is_active=True)
        self.db.add(surgeon)
        self.db.flush()
        self.db.add(DayOff(surgeon_id=surgeon.id, start_date=saturday, end_date=saturday,
                           reason="Vacation", status="approved", is_full_day=True))
        self.db.commit()
        rows = scheduler_schedule(self.db, saturday, saturday)
        self.assertEqual(["approved_off", "no_master_blocks"], sorted(row["type"] for row in rows))
        self.assertEqual({surgeon.id}, {row["surgeonId"] for row in rows})

    def test_empty_day_still_lists_every_surgeon_in_rank_order(self):
        saturday = date(2026, 10, 10)
        second = Surgeon(first_name="Chris", last_name="Johnson", sort_order=2, is_active=True)
        first = Surgeon(first_name="Jorge", last_name="Florin", sort_order=1, is_active=True)
        self.db.add_all([second, first])
        self.db.commit()

        rows = scheduler_schedule(self.db, saturday, saturday)
        self.assertEqual([first.id, second.id], [row["surgeonId"] for row in rows])
        self.assertEqual(["no_master_blocks", "no_master_blocks"], [row["type"] for row in rows])

    def test_schedule_with_case_details_requires_scheduler_login(self):
        response = TestClient(app).get(
            "/api/native/scheduler/schedule?start=2026-10-05&end=2026-10-05"
        )
        self.assertIn(response.status_code, (401, 403))


if __name__ == "__main__":
    unittest.main()
