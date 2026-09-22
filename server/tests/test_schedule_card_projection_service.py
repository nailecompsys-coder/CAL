import os
import unittest
from datetime import date, time

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("SECRET_KEY", "test-secret")

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models import Base, ClinicSchedule, DayOff, Location, SurgicalCase, Surgeon, SurgeonLocationSchedule
from app.schedule_card_projection_service import card_grid_page_data
from app.schedule_card_service import materialize_master_schedule_cards


class ScheduleCardProjectionServiceTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)

    def tearDown(self):
        Base.metadata.drop_all(self.engine)
        self.engine.dispose()

    def test_projects_only_two_permanent_cards_and_counts_matching_cases(self):
        db = self.Session()
        try:
            surgeon = Surgeon(first_name="Alex", last_name="Smith", email="as@example.com", is_active=True, staff_type="physician")
            location = Location(name="Minneola OR", abbreviation="MN-OR", location_type="hospital", is_active=True)
            db.add_all([surgeon, location])
            db.commit()
            db.add(SurgeonLocationSchedule(surgeon_id=surgeon.id, day_of_week=0, session="am", location_id=location.id, assignment_type="assigned"))
            db.commit()
            materialize_master_schedule_cards(db, start=date(2026, 9, 14), end=date(2026, 9, 18))
            db.add(SurgicalCase(surgeon_id=surgeon.id, date=date(2026, 9, 14), start_time=time(7, 15), patient_name="Patient", procedure="Procedure", location_id=location.id, status="scheduled"))
            db.commit()
            payload = card_grid_page_data(db, date(2026, 9, 14), date(2026, 9, 18))
            monday = payload["grid"][surgeon.id][date(2026, 9, 14)]
            self.assertEqual(set(monday), {"am", "pm"})
            self.assertEqual(monday["am"]["label"], "MN-OR")
            self.assertEqual(monday["am"]["count_label"], "1 case")
            self.assertTrue(monday["pm"]["is_na"])
        finally:
            db.close()

    def test_approved_time_off_overlays_existing_card_without_creating_one(self):
        db = self.Session()
        try:
            surgeon = Surgeon(first_name="Alex", last_name="Smith", email="as@example.com", is_active=True, staff_type="physician")
            db.add(surgeon)
            db.commit()
            materialize_master_schedule_cards(db, start=date(2026, 9, 14), end=date(2026, 9, 18))
            db.add(DayOff(surgeon_id=surgeon.id, start_date=date(2026, 9, 14), end_date=date(2026, 9, 14), status="approved", is_full_day=True))
            db.commit()
            payload = card_grid_page_data(db, date(2026, 9, 14), date(2026, 9, 18))
            monday = payload["grid"][surgeon.id][date(2026, 9, 14)]
            self.assertTrue(monday["am"]["is_off"])
            self.assertTrue(monday["pm"]["is_off"])
            self.assertEqual(sum(len(day) for day in payload["grid"][surgeon.id].values()), 10)
        finally:
            db.close()

    def test_1145_or_case_after_1100_clinic_counts_on_pm_card(self):
        db = self.Session()
        try:
            surgeon = Surgeon(first_name="Lucy", last_name="Woodley", email="lw@example.com", is_active=True)
            clinic = Location(name="Apopka Clinic", abbreviation="AP-OV", location_type="clinic", is_active=True)
            hospital = Location(name="Apopka OR", abbreviation="AP-OR", location_type="hospital", is_active=True)
            db.add_all([surgeon, clinic, hospital])
            db.commit()
            db.add_all([
                SurgeonLocationSchedule(surgeon_id=surgeon.id, day_of_week=0, session="am", location_id=clinic.id, assignment_type="assigned"),
                SurgeonLocationSchedule(surgeon_id=surgeon.id, day_of_week=0, session="pm", location_id=hospital.id, assignment_type="assigned"),
            ])
            db.commit()
            materialize_master_schedule_cards(db, start=date(2026, 9, 21), end=date(2026, 9, 25))
            db.add_all([
                ClinicSchedule(
                    surgeon_id=surgeon.id,
                    location_id=clinic.id,
                    date=date(2026, 9, 21),
                    session="am",
                    notes="Fax 191 visual SOT · 11:00 Clinic, Patient",
                ),
                SurgicalCase(
                    surgeon_id=surgeon.id,
                    date=date(2026, 9, 21),
                    start_time=time(11, 45),
                    patient_name="Case, Patient",
                    procedure="Procedure",
                    location_id=hospital.id,
                    status="scheduled",
                ),
            ])
            db.commit()

            payload = card_grid_page_data(db, date(2026, 9, 21), date(2026, 9, 25))
            monday = payload["grid"][surgeon.id][date(2026, 9, 21)]
            self.assertEqual(monday["am"]["count_label"], "1 visit")
            self.assertEqual(monday["pm"]["count_label"], "1 case")
        finally:
            db.close()


if __name__ == "__main__":
    unittest.main()
