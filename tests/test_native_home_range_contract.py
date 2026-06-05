import os
import unittest
from datetime import date

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models import Base, CallGroup, CallRotation, DayOff, Surgeon
from app.native_home_service import build_native_home


class NativeHomeRangeContractTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(bind=self.engine)
        self.Session = sessionmaker(bind=self.engine)

    def tearDown(self):
        Base.metadata.drop_all(bind=self.engine)
        self.engine.dispose()

    def test_native_home_range_is_inclusive_and_month_boundary_safe(self):
        db = self.Session()
        try:
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
            lauren = Surgeon(
                first_name="Lauren",
                last_name="Winter",
                email="lauren@example.com",
                staff_type="physician",
                sort_order=3,
                is_active=True,
            )
            group = CallGroup(name="Winter Garden", sort_order=1)
            db.add_all([chris, alex, lauren, group])
            db.flush()

            db.add_all([
                CallRotation(
                    call_group_id=group.id,
                    surgeon_id=chris.id,
                    date=date(2026, 6, 30),
                ),
                CallRotation(
                    call_group_id=group.id,
                    surgeon_id=alex.id,
                    date=date(2026, 7, 1),
                ),
                CallRotation(
                    call_group_id=group.id,
                    surgeon_id=lauren.id,
                    date=date(2026, 7, 4),
                ),
                DayOff(
                    surgeon_id=alex.id,
                    start_date=date(2026, 6, 29),
                    end_date=date(2026, 7, 2),
                    reason="Vacation",
                    status="approved",
                    is_full_day=True,
                ),
                DayOff(
                    surgeon_id=lauren.id,
                    start_date=date(2026, 7, 1),
                    end_date=date(2026, 7, 3),
                    reason="Requested",
                    status="pending",
                    is_full_day=True,
                ),
                DayOff(
                    surgeon_id=chris.id,
                    start_date=date(2026, 7, 5),
                    end_date=date(2026, 7, 5),
                    reason="Outside range",
                    status="approved",
                    is_full_day=True,
                ),
            ])
            db.commit()

            payload = build_native_home(db, chris, date(2026, 6, 30), date(2026, 7, 2))

            self.assertEqual(payload["range"], {"start": "2026-06-30", "end": "2026-07-02"})
            self.assertEqual([day["date"] for day in payload["days"]], ["2026-06-30", "2026-07-01", "2026-07-02"])
            self.assertEqual([day["date"] for day in payload["callSchedule"]], ["2026-06-30", "2026-07-01", "2026-07-02"])

            june_30 = payload["days"][0]
            july_1 = payload["days"][1]
            july_2 = payload["days"][2]

            self.assertEqual(june_30["callAssignments"][0]["initials"], "CJ")
            self.assertEqual(july_1["callAssignments"][0]["initials"], "AS")
            self.assertEqual(july_2["callAssignments"], [])
            self.assertNotIn("2026-07-04", [day["date"] for day in payload["callSchedule"]])

            self.assertEqual([row["initials"] for row in june_30["offSurgeons"]], ["AS"])
            self.assertEqual([row["initials"] for row in july_1["offSurgeons"]], ["AS"])
            self.assertEqual([row["initials"] for row in july_2["offSurgeons"]], ["AS"])
            self.assertEqual([row["initials"] for row in july_1["requestedOffSurgeons"]], ["LW"])
            self.assertEqual([row["initials"] for row in july_2["requestedOffSurgeons"]], ["LW"])

            self.assertFalse(any(day["date"] == "2026-07-05" for day in payload["days"]))
            self.assertFalse(any(row["initials"] == "CJ" for day in payload["days"] for row in day["offSurgeons"]))
        finally:
            db.close()


if __name__ == "__main__":
    unittest.main()
