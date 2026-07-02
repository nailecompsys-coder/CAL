import os
import unittest
from datetime import date, time

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models import (
    Base,
    CallGroup,
    CallRotation,
    ClinicSchedule,
    DayOff,
    Location,
    Meeting,
    Surgeon,
    SurgeonDayItem,
)
from app.native_home_service import build_native_home


class NativeHomeContractTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(bind=self.engine)
        self.Session = sessionmaker(bind=self.engine)

    def tearDown(self):
        Base.metadata.drop_all(bind=self.engine)
        self.engine.dispose()

    def test_native_home_payload_shape(self):
        db = self.Session()
        try:
            surgeon = Surgeon(
                first_name="Chris",
                last_name="Johnson",
                email="chris@example.com",
                staff_type="physician",
                sort_order=1,
                is_active=True,
            )
            off_surgeon = Surgeon(
                first_name="Alex",
                last_name="Smith",
                email="alex@example.com",
                staff_type="physician",
                sort_order=2,
                is_active=True,
            )
            location = Location(name="Altamonte Hosp", location_type="hospital", color="#0ea5e9", is_active=True)
            group = CallGroup(name="Winter Garden / Apopka", sort_order=1)
            db.add_all([surgeon, off_surgeon, location, group])
            db.flush()

            db.add_all([
                CallRotation(
                    call_group_id=group.id,
                    surgeon_id=surgeon.id,
                    date=date(2026, 6, 4),
                ),
                DayOff(
                    surgeon_id=surgeon.id,
                    start_date=date(2026, 6, 5),
                    end_date=date(2026, 6, 5),
                    reason="Vacation",
                    status="pending",
                    is_full_day=True,
                ),
                DayOff(
                    surgeon_id=off_surgeon.id,
                    start_date=date(2026, 6, 4),
                    end_date=date(2026, 6, 4),
                    reason="Day Off",
                    status="approved",
                    is_full_day=True,
                ),
                Meeting(
                    title="Dept Surgery",
                    date=date(2026, 6, 6),
                    start_time=time(7, 30),
                    end_time=time(8, 0),
                    location_text="Winter Garden",
                ),
                ClinicSchedule(
                    surgeon_id=surgeon.id,
                    location_id=location.id,
                    date=date(2026, 6, 4),
                    session="am",
                    assignment_type="assigned",
                ),
                SurgeonDayItem(
                    surgeon_id=surgeon.id,
                    date=date(2026, 6, 7),
                    start_time=time(14, 0),
                    title="Dentist",
                    sort_order=1,
                ),
            ])
            db.commit()

            payload = build_native_home(db, surgeon, date(2026, 6, 4), date(2026, 6, 8))

            self.assertEqual(
                {
                    "surgeon",
                    "range",
                    "days",
                    "availability",
                    "requests",
                    "dayOffSections",
                    "callGroups",
                    "surgeons",
                    "callSchedule",
                    "alerts",
                },
                set(payload.keys()),
            )
            self.assertEqual(payload["surgeon"]["id"], surgeon.id)
            self.assertEqual(payload["range"], {"start": "2026-06-04", "end": "2026-06-08"})
            self.assertEqual(len(payload["days"]), 5)

            june_4 = payload["days"][0]
            self.assertEqual(
                {"date", "dayName", "dayShort", "dayFull", "items", "offSurgeons", "requestedOffSurgeons", "callAssignments"},
                set(june_4.keys()),
            )
            self.assertEqual(june_4["date"], "2026-06-04")
            self.assertEqual(june_4["callAssignments"][0]["initials"], "CJ")
            self.assertEqual(june_4["offSurgeons"][0]["initials"], "AS")
            self.assertTrue(any(item["type"] == "clinic" for item in june_4["items"]))

            june_5 = payload["days"][1]
            self.assertTrue(any(item["type"] == "dayoff" for item in june_5["items"]))
            self.assertTrue(any(request["status"] == "pending" for request in payload["requests"]))
            self.assertEqual(payload["callGroups"], [{"id": group.id, "name": group.name}])
            self.assertFalse(any(item["type"] == "patients" for day in payload["days"] for item in day["items"]))
            self.assertIn("unreadCount", payload["alerts"])
        finally:
            db.close()


if __name__ == "__main__":
    unittest.main()
