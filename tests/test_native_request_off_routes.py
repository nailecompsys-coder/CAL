import os
import unittest
from datetime import date, timedelta
from unittest.mock import patch

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("SECRET_KEY", "test-secret")

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models import Base, DayOff, Surgeon
from app.routers.api import (
    NativeRequestOffBody,
    native_cancel_request_off,
    native_request_off,
    native_update_request_off,
)


class NativeRequestOffRoutesTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(bind=self.engine)
        self.Session = sessionmaker(bind=self.engine)

    def tearDown(self):
        Base.metadata.drop_all(bind=self.engine)
        self.engine.dispose()

    def test_create_update_and_delete_native_request_off(self):
        db = self.Session()
        try:
            surgeon = self._seed_surgeon(db)
            start = date.today() + timedelta(days=10)
            end = start + timedelta(days=2)

            create_body = NativeRequestOffBody(
                start_date=start,
                end_date=end,
                reason=" Vacation ",
                notes=" Family trip ",
                is_full_day=False,
                segments=[
                    {"date": start.isoformat(), "isFullDay": False, "start": "13:00", "end": "17:00"},
                    {"date": (start + timedelta(days=1)).isoformat(), "isFullDay": True},
                    {"date": end.isoformat(), "isFullDay": True},
                ],
            )

            with patch("app.routers.api.check_conflicts", return_value=[]), patch("app.routers.api.send_native_push_to_surgeon"):
                create_response = native_request_off(create_body, db=db, auth=(surgeon, "token"))

            self.assertTrue(create_response["ok"])
            created = create_response["request"]
            self.assertEqual(created["reason"], "Vacation")
            self.assertEqual(created["notes"], "Family trip")
            self.assertEqual(created["status"], "pending")
            self.assertFalse(created["isFullDay"])
            self.assertEqual(created["start"], "13:00")
            self.assertEqual(created["end"], "17:00")
            self.assertEqual(len(created["segments"]), 3)
            self.assertFalse(created["segments"][0]["isFullDay"])

            row = db.get(DayOff, created["id"])
            self.assertIsNotNone(row)
            self.assertEqual(row.reason, "Vacation")
            self.assertEqual(row.notes, "Family trip")

            row.status = "approved"
            row.admin_note = "Prior approval"
            db.commit()

            updated_start = start + timedelta(days=5)
            update_body = NativeRequestOffBody(
                start_date=updated_start,
                end_date=updated_start,
                reason="CME",
                notes="Course",
                is_full_day=True,
                segments=[{"date": updated_start.isoformat(), "isFullDay": True}],
            )

            with patch("app.routers.api.check_conflicts", return_value=[]), patch("app.routers.api.send_native_push_to_surgeon"):
                update_response = native_update_request_off(row.id, update_body, db=db, auth=(surgeon, "token"))

            self.assertTrue(update_response["ok"])
            updated = update_response["request"]
            self.assertEqual(updated["startDate"], updated_start.isoformat())
            self.assertEqual(updated["endDate"], updated_start.isoformat())
            self.assertEqual(updated["reason"], "CME")
            self.assertEqual(updated["notes"], "Course")
            self.assertEqual(updated["status"], "pending")
            self.assertEqual(updated["adminNote"], "")
            self.assertTrue(updated["isFullDay"])
            self.assertEqual(updated["segments"], [{"date": updated_start.isoformat(), "isFullDay": True, "start": None, "end": None}])

            refreshed = db.get(DayOff, row.id)
            self.assertEqual(refreshed.status, "pending")
            self.assertIsNone(refreshed.admin_note)

            with patch("app.routers.api.send_native_push_to_surgeon"):
                delete_response = native_cancel_request_off(row.id, db=db, auth=(surgeon, "token"))

            self.assertTrue(delete_response["ok"])
            self.assertIsNone(db.get(DayOff, row.id))
        finally:
            db.close()

    def test_create_request_returns_warnings_without_writing_on_conflict(self):
        db = self.Session()
        try:
            surgeon = self._seed_surgeon(db)
            start = date.today() + timedelta(days=7)
            body = NativeRequestOffBody(
                start_date=start,
                end_date=start,
                reason="Day Off",
                notes="",
                is_full_day=True,
            )

            with patch("app.routers.api.check_conflicts", return_value=["Clinic conflict"]), patch("app.routers.api.send_native_push_to_surgeon"):
                response = native_request_off(body, db=db, auth=(surgeon, "token"))

            self.assertFalse(response["ok"])
            self.assertIsNone(response["request"])
            self.assertEqual(response["warnings"], ["Clinic conflict"])
            self.assertEqual(db.query(DayOff).count(), 0)
        finally:
            db.close()

    def test_update_rejects_other_surgeons_request(self):
        db = self.Session()
        try:
            surgeon = self._seed_surgeon(db)
            other = Surgeon(
                first_name="Alex",
                last_name="Smith",
                email="alex@example.com",
                staff_type="physician",
                sort_order=2,
                is_active=True,
            )
            db.add(other)
            db.flush()
            row = DayOff(
                surgeon_id=other.id,
                start_date=date.today() + timedelta(days=5),
                end_date=date.today() + timedelta(days=5),
                reason="Day Off",
                status="pending",
                is_full_day=True,
            )
            db.add(row)
            db.commit()

            body = NativeRequestOffBody(
                start_date=row.start_date,
                end_date=row.end_date,
                reason="Day Off",
                notes="",
                is_full_day=True,
            )

            with self.assertRaises(HTTPException) as ctx:
                native_update_request_off(row.id, body, db=db, auth=(surgeon, "token"))

            self.assertEqual(ctx.exception.status_code, 404)
        finally:
            db.close()

    def _seed_surgeon(self, db):
        surgeon = Surgeon(
            first_name="Chris",
            last_name="Johnson",
            email="chris@example.com",
            staff_type="physician",
            sort_order=1,
            is_active=True,
        )
        db.add(surgeon)
        db.commit()
        db.refresh(surgeon)
        return surgeon


if __name__ == "__main__":
    unittest.main()
