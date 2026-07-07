import os
import unittest
from datetime import date, timedelta

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.admin_clinic_schedule_action_service import copy_clinic_week
from app.admin_clinic_schedule_page_service import clinic_schedule_sort_key
from app.migrate_location_admin_fields import normalize_office_location_name
from app.models import Base, ClinicSchedule, Location, Surgeon


class AdminClinicScheduleTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(bind=self.engine)
        self.Session = sessionmaker(bind=self.engine)

    def tearDown(self):
        Base.metadata.drop_all(bind=self.engine)
        self.engine.dispose()

    def test_clinic_schedule_sort_key_places_am_pm_then_full(self):
        rows = [
            ClinicSchedule(id=10, session="pm"),
            ClinicSchedule(id=11, session="full"),
            ClinicSchedule(id=12, session="am"),
        ]

        ordered = sorted(rows, key=clinic_schedule_sort_key)

        self.assertEqual([row.session for row in ordered], ["am", "pm", "full"])

    def test_copy_clinic_week_filters_to_selected_surgeon_only(self):
        db = self.Session()
        try:
            chris = self._surgeon(db, "Chris", "Johnson")
            alex = self._surgeon(db, "Alex", "Schroeder")
            clinic = Location(name="Winter Garden Clinic", abbreviation="WG", location_type="clinic", is_active=True)
            db.add(clinic)
            db.flush()

            today = date.today()
            src_start = today - timedelta(days=today.weekday())
            db.add_all([
                ClinicSchedule(surgeon_id=chris.id, location_id=clinic.id, date=src_start, session="am"),
                ClinicSchedule(surgeon_id=alex.id, location_id=clinic.id, date=src_start, session="pm"),
            ])
            db.commit()

            result = copy_clinic_week(db, 0, str(chris.id))

            self.assertTrue(result["ok"])
            self.assertEqual(result["created"], 1)
            next_week = src_start + timedelta(days=7)
            copied = db.query(ClinicSchedule).filter(ClinicSchedule.date == next_week).all()
            self.assertEqual(len(copied), 1)
            self.assertEqual(copied[0].surgeon_id, chris.id)
            self.assertEqual(copied[0].session, "am")
        finally:
            db.close()

    def test_location_name_normalization_changes_office_word_to_clinic(self):
        self.assertEqual(normalize_office_location_name("Winter Garden Office"), "Winter Garden Clinic")
        self.assertEqual(normalize_office_location_name("Office"), "Clinic")
        self.assertEqual(normalize_office_location_name("Main Clinic"), "Main Clinic")

    def _surgeon(self, db, first_name, last_name):
        row = Surgeon(
            first_name=first_name,
            last_name=last_name,
            email=f"{first_name.lower()}.{last_name.lower()}@example.com",
            is_active=True,
            staff_type="physician",
        )
        db.add(row)
        db.flush()
        return row


if __name__ == "__main__":
    unittest.main()
