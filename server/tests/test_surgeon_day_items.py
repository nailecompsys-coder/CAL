import json
import os
import unittest
from datetime import date, timedelta
from unittest.mock import MagicMock

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("SECRET_KEY", "test-secret")

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models import Base, Surgeon, SurgeonDayItem
from app.routers.surgeon_day_items import DayItemCreate, api_create_day_item


class SurgeonDayItemsRangeTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(bind=self.engine)
        self.Session = sessionmaker(bind=self.engine)

    def tearDown(self):
        Base.metadata.drop_all(bind=self.engine)
        self.engine.dispose()

    def _surgeon(self, db):
        row = Surgeon(
            first_name="Lars",
            last_name="Nelson",
            email="ln@example.com",
            is_active=True,
            staff_type="physician",
        )
        db.add(row)
        db.flush()
        return row

    def test_create_single_day_still_works(self):
        db = self.Session()
        try:
            surgeon = self._surgeon(db)
            day = date.today() + timedelta(days=3)
            response = api_create_day_item(
                DayItemCreate(date=day, title="Personal appointment", notes="kids"),
                db=db,
                auth=(surgeon, MagicMock()),
            )
            payload = json.loads(response.body)
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["count"], 1)
            self.assertEqual(payload["item"]["title"], "Personal appointment")
            self.assertEqual(db.query(SurgeonDayItem).count(), 1)
            self.assertEqual(db.query(SurgeonDayItem).one().date, day)
        finally:
            db.close()

    def test_create_day_range_places_one_item_per_day(self):
        db = self.Session()
        try:
            surgeon = self._surgeon(db)
            start = date.today() + timedelta(days=5)
            end = start + timedelta(days=3)
            response = api_create_day_item(
                DayItemCreate(
                    date=start,
                    end_date=end,
                    title="Travel",
                    notes="family trip",
                    start_time="09:00",
                    end_time="10:00",
                ),
                db=db,
                auth=(surgeon, MagicMock()),
            )
            payload = json.loads(response.body)
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["count"], 4)
            self.assertEqual(len(payload["items"]), 4)
            rows = (
                db.query(SurgeonDayItem)
                .filter(SurgeonDayItem.surgeon_id == surgeon.id)
                .order_by(SurgeonDayItem.date)
                .all()
            )
            self.assertEqual([row.date for row in rows], [
                start,
                start + timedelta(days=1),
                start + timedelta(days=2),
                start + timedelta(days=3),
            ])
            self.assertTrue(all(row.title == "Travel" for row in rows))
            self.assertTrue(all(row.start_time.strftime("%H:%M") == "09:00" for row in rows))
        finally:
            db.close()

    def test_create_rejects_inverted_and_too_long_ranges(self):
        db = self.Session()
        try:
            surgeon = self._surgeon(db)
            start = date.today() + timedelta(days=2)
            with self.assertRaises(HTTPException) as inverted:
                api_create_day_item(
                    DayItemCreate(date=start, end_date=start - timedelta(days=1), title="Travel"),
                    db=db,
                    auth=(surgeon, MagicMock()),
                )
            self.assertEqual(inverted.exception.status_code, 400)

            with self.assertRaises(HTTPException) as too_long:
                api_create_day_item(
                    DayItemCreate(
                        date=start,
                        end_date=start + timedelta(days=31),
                        title="Travel",
                    ),
                    db=db,
                    auth=(surgeon, MagicMock()),
                )
            self.assertEqual(too_long.exception.status_code, 400)
            self.assertEqual(db.query(SurgeonDayItem).count(), 0)
        finally:
            db.close()


if __name__ == "__main__":
    unittest.main()
