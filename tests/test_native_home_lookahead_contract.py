import os
import unittest
from datetime import date, time, timedelta

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models import Base, Meeting, Surgeon, SurgeonDayItem
from app.native_home_service import build_native_home


class NativeHomeLookaheadContractTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(bind=self.engine)
        self.Session = sessionmaker(bind=self.engine)

    def tearDown(self):
        Base.metadata.drop_all(bind=self.engine)
        self.engine.dispose()

    def test_native_home_includes_meeting_and_personal_items_through_30_days_only(self):
        db = self.Session()
        try:
            today = date.today()
            end = today + timedelta(days=30)
            outside = today + timedelta(days=31)

            surgeon = Surgeon(
                first_name="Chris",
                last_name="Johnson",
                email="chris@example.com",
                staff_type="physician",
                sort_order=1,
                is_active=True,
            )
            db.add(surgeon)
            db.flush()

            db.add_all([
                Meeting(
                    title="Dept Surgery",
                    date=end,
                    start_time=time(7, 30),
                    end_time=time(8, 0),
                    location_text="Winter Garden",
                ),
                Meeting(
                    title="Outside Lookahead",
                    date=outside,
                    start_time=time(9, 0),
                    end_time=time(10, 0),
                    location_text="Altamonte",
                ),
                SurgeonDayItem(
                    surgeon_id=surgeon.id,
                    date=today + timedelta(days=14),
                    start_time=time(14, 0),
                    title="Dentist",
                    notes="Personal appointment",
                    sort_order=1,
                ),
                SurgeonDayItem(
                    surgeon_id=surgeon.id,
                    date=outside,
                    start_time=time(11, 0),
                    title="Outside Personal",
                    sort_order=1,
                ),
            ])
            db.commit()

            payload = build_native_home(db, surgeon, today, end)

            self.assertEqual(payload["range"], {"start": today.isoformat(), "end": end.isoformat()})
            self.assertEqual(len(payload["days"]), 31)

            items_by_date = {
                day["date"]: day["items"]
                for day in payload["days"]
            }
            personal_items = items_by_date[(today + timedelta(days=14)).isoformat()]
            end_items = items_by_date[end.isoformat()]
            all_titles = [item["title"] for day in payload["days"] for item in day["items"]]

            self.assertTrue(any(item["type"] == "personal" and item["title"] == "Dentist" for item in personal_items))
            self.assertTrue(any(item["type"] == "meeting" and item["title"] == "Dept Surgery" for item in end_items))
            self.assertNotIn("Outside Lookahead", all_titles)
            self.assertNotIn("Outside Personal", all_titles)
            self.assertFalse(any(day["date"] == outside.isoformat() for day in payload["days"]))
        finally:
            db.close()


if __name__ == "__main__":
    unittest.main()
