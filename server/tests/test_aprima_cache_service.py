import os
import unittest
from datetime import date, datetime, timezone
from unittest.mock import patch

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("SECRET_KEY", "test-secret")

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.aprima_cache_service import (
    cache_is_usable,
    main_office_patients_by_weekday,
    patient_appointments_for_api,
    row_content_hash,
    run_aprima_sync,
    sync_status_payload,
)
from app.models import AprimaCachedAppointment, AprimaSyncState, Base, Surgeon


def _row(appt_id: str, day: str, initials: str = "JB", site: str = "Clermont Office") -> dict:
    return {
        "id": appt_id,
        "date": day,
        "start": "09:00",
        "end": "09:30",
        "timeZone": "America/New_York",
        "surgeonInitials": initials,
        "surgeonName": "Jorge",
        "patientName": f"Patient {appt_id}",
        "mrn": appt_id,
        "appointmentType": "Office Visit",
        "status": "Scheduled",
        "reason": "",
        "serviceSite": site,
        "room": "1",
    }


class AprimaCacheServiceTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)
        self.db = self.Session()
        self.surgeon = Surgeon(
            first_name="Jorge",
            last_name="Barnes",
            email="jb@example.com",
            is_active=True,
            staff_type="physician",
        )
        self.db.add(self.surgeon)
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def test_row_content_hash_changes_when_time_moves(self):
        a = _row("1", "2026-07-10")
        b = dict(a)
        b["start"] = "10:00"
        self.assertNotEqual(row_content_hash(a), row_content_hash(b))

    @patch("app.aprima_cache_service.send_native_push_to_surgeon")
    @patch("app.aprima_cache_service.fetch_aprima_meetings")
    @patch("app.aprima_cache_service.fetch_patient_appointments")
    @patch("app.aprima_cache_service.practice_today", return_value=date(2026, 7, 9))
    def test_sync_upserts_and_marks_ok(self, _today, fetch_patients, fetch_meetings, push):
        fetch_patients.return_value = [_row("a1", "2026-07-09"), _row("a2", "2026-07-10")]
        fetch_meetings.return_value = {"meetings": [], "warning": None}

        result = run_aprima_sync(self.db, notify=True)
        self.assertTrue(result["ok"])
        self.assertEqual(result["patients"], 2)
        self.assertEqual(self.db.query(AprimaCachedAppointment).count(), 2)
        status = sync_status_payload(self.db)
        self.assertEqual(status["status"], "ok")
        self.assertTrue(cache_is_usable(self.db))
        # First seed should not push.
        push.assert_not_called()

    @patch("app.aprima_cache_service.send_native_push_to_surgeon")
    @patch("app.aprima_cache_service.fetch_aprima_meetings")
    @patch("app.aprima_cache_service.fetch_patient_appointments")
    @patch("app.aprima_cache_service.practice_today", return_value=date(2026, 7, 9))
    def test_sync_detects_cancel_and_notifies(self, _today, fetch_patients, fetch_meetings, push):
        fetch_patients.return_value = [_row("a1", "2026-07-09")]
        fetch_meetings.return_value = {"meetings": [], "warning": None}
        run_aprima_sync(self.db, notify=True)

        fetch_patients.return_value = []  # cancelled / removed
        result = run_aprima_sync(self.db, notify=True)
        self.assertTrue(result["ok"])
        self.assertEqual(self.db.query(AprimaCachedAppointment).count(), 0)
        push.assert_called()
        self.assertEqual(result["changedSurgeons"], 1)

    @patch("app.aprima_cache_service.fetch_patient_appointments")
    @patch("app.aprima_cache_service.practice_today", return_value=date(2026, 7, 9))
    def test_api_prefers_fresh_cache(self, _today, fetch_patients):
        state = AprimaSyncState(
            last_status="ok",
            last_finished_at=datetime.now(timezone.utc).replace(tzinfo=None),
            patient_count=1,
            meeting_count=0,
            window_start=date(2026, 7, 9),
            window_end=date(2026, 7, 30),
            content_fingerprint="abc",
        )
        self.db.add(state)
        self.db.add(
            AprimaCachedAppointment(
                appointment_id="c1",
                kind="patient",
                date=date(2026, 7, 9),
                surgeon_initials="JB",
                content_hash="x",
                payload_json=(
                    '{"id":"c1","date":"2026-07-09","start":"09:00","end":"09:30",'
                    '"surgeonInitials":"JB","surgeonName":"Jorge","patientName":"Cached",'
                    '"mrn":"1","appointmentType":"Office Visit","status":"Scheduled",'
                    '"reason":"","serviceSite":"Clermont Office","room":"1",'
                    '"timeZone":"America/New_York"}'
                ),
                synced_at=datetime.now(timezone.utc).replace(tzinfo=None),
            )
        )
        self.db.commit()

        payload = patient_appointments_for_api(
            self.db, date(2026, 7, 9), date(2026, 7, 15), surgeon=self.surgeon
        )
        self.assertEqual(payload["source"], "cache")
        self.assertEqual(len(payload["appointments"]), 1)
        fetch_patients.assert_not_called()

        week = main_office_patients_by_weekday(self.db, date(2026, 7, 9))
        self.assertEqual(week["total"], 1)
        self.assertEqual(week["source"], "cache")


if __name__ == "__main__":
    unittest.main()
