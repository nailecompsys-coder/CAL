import json
import os
import unittest
from datetime import date, timedelta

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models import Base, DayOff, Surgeon
from app.native_support import (
    native_day_off_sections,
    normalize_day_off_segments,
    serialize_day_off,
    validate_day_off_segments,
)


class NativeDayOffContractTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(bind=self.engine)
        self.Session = sessionmaker(bind=self.engine)

    def tearDown(self):
        Base.metadata.drop_all(bind=self.engine)
        self.engine.dispose()

    def test_native_day_off_sections_include_pending_approved_and_segments(self):
        db = self.Session()
        try:
            today = date.today()
            start = today + timedelta(days=10)
            end = start + timedelta(days=3)
            next_month = _add_month(today, 1)

            chris = Surgeon(
                first_name="Chris",
                last_name="Johnson",
                email="chris@example.com",
                staff_type="physician",
                sort_order=1,
                is_active=True,
            )
            alex = Surgeon(
                first_name="Alex",
                last_name="Smith",
                email="alex@example.com",
                staff_type="physician",
                sort_order=2,
                is_active=True,
            )
            staff = Surgeon(
                first_name="Pat",
                last_name="Staff",
                email="staff@example.com",
                staff_type="staff",
                sort_order=3,
                is_active=True,
            )
            db.add_all([chris, alex, staff])
            db.flush()

            mixed_segments = normalize_day_off_segments(
                start,
                end,
                True,
                None,
                None,
                [
                    {"date": start.isoformat(), "isFullDay": False, "start": "13:00", "end": "17:00"},
                    {"date": (start + timedelta(days=1)).isoformat(), "isFullDay": True},
                    {"date": (start + timedelta(days=2)).isoformat(), "isFullDay": True},
                    {"date": end.isoformat(), "isFullDay": True},
                ],
            )
            validate_day_off_segments(mixed_segments)

            pending = DayOff(
                surgeon_id=chris.id,
                start_date=start,
                end_date=end,
                reason="Vacation",
                notes="Family trip",
                status="pending",
                is_full_day=False,
                segments=json.dumps(mixed_segments),
            )
            approved = DayOff(
                surgeon_id=alex.id,
                start_date=next_month,
                end_date=next_month,
                reason="Conference",
                status="approved",
                is_full_day=True,
            )
            denied = DayOff(
                surgeon_id=chris.id,
                start_date=start + timedelta(days=5),
                end_date=start + timedelta(days=5),
                reason="Denied should not show",
                status="denied",
                is_full_day=True,
            )
            staff_request = DayOff(
                surgeon_id=staff.id,
                start_date=start,
                end_date=start,
                reason="Staff should not show to physician",
                status="approved",
                is_full_day=True,
            )
            db.add_all([pending, approved, denied, staff_request])
            db.commit()

            serialized = serialize_day_off(pending)
            self.assertEqual(serialized["status"], "pending")
            self.assertEqual(serialized["surgeonInitials"], "CJ")
            self.assertEqual(serialized["segments"], mixed_segments)
            self.assertFalse(serialized["segments"][0]["isFullDay"])
            self.assertEqual(serialized["segments"][0]["start"], "13:00")
            self.assertEqual(serialized["segments"][0]["end"], "17:00")
            self.assertEqual(sum(1 for item in serialized["segments"] if not item["isFullDay"]), 1)

            sections = native_day_off_sections(db, chris)
            self.assertGreaterEqual(len(sections), 12)

            section_requests = [request for section in sections for request in section["requests"]]
            request_ids = {request["id"] for request in section_requests}

            self.assertIn(pending.id, request_ids)
            self.assertIn(approved.id, request_ids)
            self.assertNotIn(denied.id, request_ids)
            self.assertNotIn(staff_request.id, request_ids)

            pending_section = next(
                section
                for section in sections
                if any(request["id"] == pending.id for request in section["requests"])
            )
            self.assertIn("SURGEONS", pending_section["header"])
            self.assertTrue(any(section["isCurrentMonth"] for section in sections))
        finally:
            db.close()

    def test_partial_day_segments_require_valid_time_window(self):
        segments = normalize_day_off_segments(
            date.today(),
            date.today(),
            False,
            "13:00",
            "12:00",
            None,
        )

        with self.assertRaises(HTTPException) as ctx:
            validate_day_off_segments(segments)

        self.assertEqual(ctx.exception.status_code, 400)


def _add_month(value: date, months: int) -> date:
    month_index = value.month - 1 + months
    year = value.year + month_index // 12
    month = month_index % 12 + 1
    return date(year, month, min(value.day, 28))


if __name__ == "__main__":
    unittest.main()
