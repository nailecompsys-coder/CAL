import os
import unittest
from datetime import date, time, timedelta
from unittest.mock import patch

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("SECRET_KEY", "test-secret")

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models import Availability, Base, NativePushToken, Surgeon, SurgicalCase
from app.routers.native_api import (
    NativeAvailabilityBody,
    NativeAvailabilityRow,
    NativePushTokenBody,
    NativeSurgeryNotesBody,
    native_push_token,
    native_save_availability,
    native_save_surgery_notes,
)


class NativeMiscRoutesTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(bind=self.engine)
        self.Session = sessionmaker(bind=self.engine)

    def tearDown(self):
        Base.metadata.drop_all(bind=self.engine)
        self.engine.dispose()

    def test_push_token_upserts_existing_token_to_current_surgeon(self):
        db = self.Session()
        try:
            first = self._seed_surgeon(db, "Chris", "Johnson", "chris@example.com")
            second = self._seed_surgeon(db, "Alex", "Smith", "alex@example.com")
            token = NativePushToken(surgeon_id=first.id, token="ExponentPushToken[abc]", platform="ios", is_active=False)
            db.add(token)
            db.commit()

            response = native_push_token(
                NativePushTokenBody(
                    token=" ExponentPushToken[abc] ",
                    platform="ios",
                    provider="apns",
                    deviceName="iPhone",
                ),
                db=db,
                auth=(second, None),
            )

            self.assertTrue(response["ok"])
            db.refresh(token)
            self.assertEqual(token.surgeon_id, second.id)
            self.assertTrue(token.is_active)
            self.assertEqual(token.provider, "apns")
            self.assertEqual(token.device_name, "iPhone")
        finally:
            db.close()

    def test_push_token_rejects_empty_token(self):
        db = self.Session()
        try:
            surgeon = self._seed_surgeon(db, "Chris", "Johnson", "chris@example.com")
            with self.assertRaises(HTTPException) as ctx:
                native_push_token(NativePushTokenBody(token="   "), db=db, auth=(surgeon, None))
            self.assertEqual(ctx.exception.status_code, 400)
        finally:
            db.close()

    def test_save_availability_creates_and_updates_rows(self):
        db = self.Session()
        try:
            surgeon = self._seed_surgeon(db, "Chris", "Johnson", "chris@example.com")
            target = date.today() + timedelta(days=3)

            with patch("app.routers.native_api.check_conflicts", return_value=["Clinic conflict"]):
                response = native_save_availability(
                    NativeAvailabilityBody(days=[
                        NativeAvailabilityRow(date=target, isAvailable=False, start="07:00", end="12:00"),
                    ]),
                    db=db,
                    auth=(surgeon, "token"),
                )

            self.assertTrue(response["ok"])
            self.assertEqual(response["warnings"], ["Clinic conflict"])
            row = db.query(Availability).filter(Availability.surgeon_id == surgeon.id, Availability.date == target).one()
            self.assertFalse(row.is_available)
            self.assertEqual(row.start_time, time(7, 0))
            self.assertEqual(row.end_time, time(12, 0))

            with patch("app.routers.native_api.check_conflicts", return_value=[]):
                response = native_save_availability(
                    NativeAvailabilityBody(days=[
                        NativeAvailabilityRow(date=target, isAvailable=True, start=None, end=None),
                    ]),
                    db=db,
                    auth=(surgeon, "token"),
                )

            self.assertTrue(response["ok"])
            db.refresh(row)
            self.assertTrue(row.is_available)
            self.assertIsNone(row.start_time)
            self.assertIsNone(row.end_time)
        finally:
            db.close()

    def test_surgery_notes_save_and_reject_other_surgeon_case(self):
        db = self.Session()
        try:
            surgeon = self._seed_surgeon(db, "Chris", "Johnson", "chris@example.com")
            other = self._seed_surgeon(db, "Alex", "Smith", "alex@example.com")
            own_case = SurgicalCase(
                surgeon_id=surgeon.id,
                date=date.today() + timedelta(days=1),
                start_time=time(8, 0),
                patient_name="Test Patient",
                procedure="Procedure",
            )
            other_case = SurgicalCase(
                surgeon_id=other.id,
                date=date.today() + timedelta(days=1),
                start_time=time(9, 0),
                patient_name="Other Patient",
                procedure="Other Procedure",
            )
            db.add_all([own_case, other_case])
            db.commit()

            with patch("app.routers.native_api.send_native_push_to_surgeon"):
                response = native_save_surgery_notes(
                    own_case.id,
                    NativeSurgeryNotesBody(notes=" Needs follow up "),
                    db=db,
                    auth=(surgeon, "token"),
                )

            self.assertTrue(response["ok"])
            db.refresh(own_case)
            self.assertEqual(own_case.surgeon_notes, "Needs follow up")

            with self.assertRaises(HTTPException) as ctx:
                native_save_surgery_notes(
                    other_case.id,
                    NativeSurgeryNotesBody(notes="Nope"),
                    db=db,
                    auth=(surgeon, "token"),
                )
            self.assertEqual(ctx.exception.status_code, 404)
        finally:
            db.close()

    def _seed_surgeon(self, db, first_name: str, last_name: str, email: str) -> Surgeon:
        surgeon = Surgeon(
            first_name=first_name,
            last_name=last_name,
            email=email,
            staff_type="physician",
            is_active=True,
        )
        db.add(surgeon)
        db.commit()
        db.refresh(surgeon)
        return surgeon


if __name__ == "__main__":
    unittest.main()
