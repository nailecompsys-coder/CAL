import os
import unittest
from datetime import date, timedelta

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

from app.admin_dayoff_service import dayoff_is_current_or_future
from app.models import DayOff


class AdminDayOffServiceTest(unittest.TestCase):
    def test_dayoff_archive_cutoff_keeps_today_and_future_only(self):
        today = date(2026, 7, 7)

        past = DayOff(start_date=today - timedelta(days=3), end_date=today - timedelta(days=1))
        active = DayOff(start_date=today - timedelta(days=1), end_date=today)
        future = DayOff(start_date=today + timedelta(days=1), end_date=today + timedelta(days=2))

        self.assertFalse(dayoff_is_current_or_future(past, today))
        self.assertTrue(dayoff_is_current_or_future(active, today))
        self.assertTrue(dayoff_is_current_or_future(future, today))


if __name__ == "__main__":
    unittest.main()
