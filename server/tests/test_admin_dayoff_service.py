import os
import unittest
from datetime import date, timedelta
from types import SimpleNamespace

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

from app.admin_dayoff_service import (
    _bar_for_month,
    dayoff_is_current_or_future,
    gantt_rows,
    month_window,
)
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

    def test_month_window_offset(self):
        window = month_window(0)
        self.assertEqual(window["month_offset"], 0)
        self.assertEqual(window["days_in_month"], len(window["day_numbers"]))
        self.assertEqual(window["month_start"].day, 1)
        self.assertEqual(window["month_end"].day, window["days_in_month"])

    def test_bar_for_month_clips_and_positions(self):
        month_start = date(2026, 7, 1)
        month_end = date(2026, 7, 31)
        dayoff = DayOff(
            id=1,
            status="approved",
            reason="Vacation",
            notes="",
            start_date=date(2026, 6, 28),
            end_date=date(2026, 7, 5),
        )
        bar = _bar_for_month(dayoff, month_start, month_end, 31)
        self.assertIsNotNone(bar)
        self.assertEqual(bar["labelStart"], "1")
        self.assertEqual(bar["labelEnd"], "5")
        self.assertEqual(bar["spanDays"], 5)
        self.assertEqual(bar["leftPct"], 0.0)
        self.assertAlmostEqual(bar["widthPct"], 5 / 31 * 100, places=3)

    def test_gantt_rows_stacks_overlapping_and_skips_denied(self):
        surgeons = [
            SimpleNamespace(id=1, last_name="Alpha", full_name="A Alpha", initials="AA"),
            SimpleNamespace(id=2, last_name="Beta", full_name="B Beta", initials="BB"),
        ]
        dayoffs = [
            DayOff(
                id=10,
                surgeon_id=1,
                status="approved",
                reason="Vacation",
                notes="",
                start_date=date(2026, 7, 1),
                end_date=date(2026, 7, 10),
            ),
            DayOff(
                id=11,
                surgeon_id=1,
                status="pending",
                reason="CME",
                notes="",
                start_date=date(2026, 7, 5),
                end_date=date(2026, 7, 8),
            ),
            DayOff(
                id=12,
                surgeon_id=1,
                status="denied",
                reason="Nope",
                notes="",
                start_date=date(2026, 7, 12),
                end_date=date(2026, 7, 14),
            ),
            DayOff(
                id=13,
                surgeon_id=2,
                status="approved",
                reason="Day Off",
                notes="",
                start_date=date(2026, 8, 1),
                end_date=date(2026, 8, 3),
            ),
        ]
        rows = gantt_rows(
            surgeons,
            dayoffs,
            month_start=date(2026, 7, 1),
            month_end=date(2026, 7, 31),
            days_in_month=31,
        )
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["surgeon"].id, 1)
        self.assertTrue(rows[0]["hasBars"])
        self.assertEqual(len(rows[0]["bars"]), 2)
        self.assertEqual(rows[0]["laneCount"], 2)
        lanes = {bar["lane"] for bar in rows[0]["bars"]}
        self.assertEqual(lanes, {0, 1})
        self.assertFalse(rows[1]["hasBars"])


if __name__ == "__main__":
    unittest.main()
