import os
import unittest
from datetime import date, datetime
from unittest.mock import patch

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("SECRET_KEY", "test-secret")

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models import Base, Surgeon
from app.native_patient_schedule_service import APPOINTMENT_SQL, _local_bounds_for_dates, _serialize_row
from app.routers.native_api import native_patient_schedule


class NativePatientScheduleRouteTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(bind=self.engine)
        self.Session = sessionmaker(bind=self.engine)

    def tearDown(self):
        Base.metadata.drop_all(bind=self.engine)
        self.engine.dispose()

    def test_native_patient_schedule_returns_aprima_payload(self):
        db = self.Session()
        try:
            surgeon = self._seed_surgeon(db)
            expected = {
                "range": {"start": "2026-06-12", "end": "2026-06-18"},
                "appointments": [
                    {
                        "id": "appt-1",
                        "date": "2026-06-12",
                        "start": "08:00",
                        "end": "08:30",
                        "timeZone": "America/New_York",
                        "surgeonInitials": "CJ",
                        "surgeonName": "Chris Johnson",
                        "patientName": "Patient, Test",
                        "mrn": "123",
                        "appointmentType": "Office Visit",
                        "status": "Scheduled",
                        "reason": "Consult",
                        "serviceSite": "Winter Garden",
                        "room": "1",
                    }
                ],
            }

            with patch("app.routers.native_api.native_patient_schedule_service", return_value=expected) as service:
                response = native_patient_schedule(
                    "2026-06-12",
                    "2026-06-18",
                    auth=(surgeon, "token"),
                )

            self.assertEqual(response, expected)
            service.assert_called_once_with(date(2026, 6, 12), date(2026, 6, 18), surgeon=surgeon)
        finally:
            db.close()

    def test_aprima_query_bounds_use_eastern_dates_as_aprima_utc_datetimes(self):
        start, end = _local_bounds_for_dates(date(2026, 6, 15), date(2026, 6, 21))

        self.assertEqual(start, datetime(2026, 6, 15, 4, 0))
        self.assertEqual(end, datetime(2026, 6, 22, 4, 0))

    def test_aprima_rows_are_serialized_as_eastern_military_time(self):
        row = _serialize_row({
            "appointment_id": "appt-1",
            "aprima_start_datetime": datetime(2026, 6, 15, 12, 20),
            "aprima_end_datetime": datetime(2026, 6, 15, 12, 30),
            "surgeon_initials": "LW",
            "surgeon_name": "Lucille Woodley",
            "patient_name": "Patient, Test",
            "mrn": "123",
            "appointment_type": "Office Visit",
            "status": "Scheduled",
            "reason": "Consult",
            "service_site": "Winter Garden",
            "room": "1",
        })

        self.assertEqual(row["date"], "2026-06-15")
        self.assertEqual(row["start"], "08:20")
        self.assertEqual(row["end"], "08:30")
        self.assertEqual(row["timeZone"], "America/New_York")

    def test_aprima_query_only_reads_visible_scheduled_patient_appointments(self):
        self.assertNotIn("AT TIME ZONE", APPOINTMENT_SQL)
        self.assertIn("a.StartDateTime AS AprimaStartDateTime", APPOINTMENT_SQL)
        self.assertIn("las.ShowOnSchedule = 1", APPOINTMENT_SQL)
        self.assertIn("a.PatientUid IS NOT NULL", APPOINTMENT_SQL)
        self.assertIn("pt.Inactive = 0", APPOINTMENT_SQL)
        self.assertIn("NOT LIKE '%RECALL%'", APPOINTMENT_SQL)
        self.assertIn("NOT LIKE '%POSSIBLE%'", APPOINTMENT_SQL)

    def _seed_surgeon(self, db) -> Surgeon:
        surgeon = Surgeon(
            first_name="Chris",
            last_name="Johnson",
            email="chris@example.com",
            staff_type="physician",
            is_active=True,
        )
        db.add(surgeon)
        db.commit()
        db.refresh(surgeon)
        return surgeon


if __name__ == "__main__":
    unittest.main()
