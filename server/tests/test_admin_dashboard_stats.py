import os
import unittest
from datetime import date, time
from unittest.mock import patch

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.admin_dashboard_stats_service import (
    clinic_visits_today_count,
    dashboard_today_volume_stats,
    surgical_cases_today_count,
)
from app.models import Base, ClinicSchedule, Location, Surgeon, SurgicalCase


class AdminDashboardStatsTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(bind=self.engine)
        self.Session = sessionmaker(bind=self.engine)
        self.day = date(2026, 7, 23)

    def tearDown(self):
        Base.metadata.drop_all(bind=self.engine)
        self.engine.dispose()

    def _surgeon(self, db, first="Chris", last="Johnson"):
        row = Surgeon(
            first_name=first,
            last_name=last,
            email=f"{first.lower()}.{last.lower()}@example.com",
            is_active=True,
            staff_type="physician",
        )
        db.add(row)
        db.flush()
        return row

    def test_surgical_cases_today_excludes_cancelled_and_other_days(self):
        db = self.Session()
        try:
            surgeon = self._surgeon(db)
            loc = Location(name="WG OR", abbreviation="WG-OR", location_type="hospital", is_active=True)
            db.add(loc)
            db.flush()
            db.add_all([
                SurgicalCase(
                    surgeon_id=surgeon.id,
                    date=self.day,
                    start_time=time(8, 0),
                    patient_name="A, PATIENT",
                    procedure="ORIF",
                    location_id=loc.id,
                    status="scheduled",
                ),
                SurgicalCase(
                    surgeon_id=surgeon.id,
                    date=self.day,
                    start_time=time(9, 0),
                    patient_name="B, PATIENT",
                    procedure="Scope",
                    location_id=loc.id,
                    status="cancelled",
                ),
                SurgicalCase(
                    surgeon_id=surgeon.id,
                    date=date(2026, 7, 24),
                    start_time=time(8, 0),
                    patient_name="C, PATIENT",
                    procedure="ORIF",
                    location_id=loc.id,
                    status="scheduled",
                ),
            ])
            db.commit()
            self.assertEqual(surgical_cases_today_count(db, self.day), 1)
        finally:
            db.close()

    @patch("app.admin_dashboard_stats_service.patient_appointments_for_api")
    def test_clinic_visits_sum_aprima_non_surgery_and_fax_segments(self, mock_api):
        mock_api.return_value = {
            "appointments": [
                {"appointmentType": "Office Visit", "serviceSite": "Apopka Clinic"},
                {"appointmentType": "Surgery", "serviceSite": "AHWG-Outpt"},
                {"appointmentType": "Follow Up", "serviceSite": "Minneola Clinic"},
            ]
        }
        db = self.Session()
        try:
            surgeon = self._surgeon(db)
            clinic = Location(name="WG Clinic", abbreviation="WG", location_type="clinic", is_active=True)
            db.add(clinic)
            db.flush()
            db.add(ClinicSchedule(
                surgeon_id=surgeon.id,
                location_id=clinic.id,
                date=self.day,
                session="am",
                assignment_type="assigned",
                notes="Desk fax 13:00 NIEVES, ROSA; 13:10 PINDER, JOE",
            ))
            db.commit()
            # 2 Aprima clinic + 2 fax segments; Surgery type excluded
            self.assertEqual(clinic_visits_today_count(db, self.day), 4)
            stats = dashboard_today_volume_stats(db, self.day)
            self.assertEqual(stats["clinic_visits_today"], 4)
            self.assertEqual(stats["surgical_cases_today"], 0)
        finally:
            db.close()


if __name__ == "__main__":
    unittest.main()
