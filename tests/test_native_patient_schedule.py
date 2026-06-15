import os
import unittest
from datetime import date
from unittest.mock import patch

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("SECRET_KEY", "test-secret")

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models import Base, Surgeon
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
            service.assert_called_once_with(date(2026, 6, 12), date(2026, 6, 18))
        finally:
            db.close()

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
