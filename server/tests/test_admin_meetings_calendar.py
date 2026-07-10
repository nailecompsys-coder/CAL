import os
import unittest
from datetime import date, time
from types import SimpleNamespace

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("SECRET_KEY", "test-secret")

from app.admin_meeting_service import calendar_events_by_day, month_schedule_days


class AdminMeetingsCalendarTest(unittest.TestCase):
    def test_month_schedule_days_pads_sunday_start(self):
        # July 2026 starts on Wednesday → pad_start 3 (Sun/Mon/Tue empty)
        data = month_schedule_days(0)
        # Use a fixed offset relative to today is flaky; just assert shape.
        self.assertIn("schedule_days", data)
        self.assertTrue(1 <= len(data["schedule_days"]) <= 31)
        self.assertEqual(data["pad_start"], (data["schedule_days"][0].weekday() + 1) % 7)

    def test_calendar_events_merge_cal_and_aprima_by_day(self):
        day = date(2026, 7, 15)
        cal = SimpleNamespace(
            id=54,
            title="PCP Meeting with Joel",
            date=day,
            start_time=time(12, 0),
            end_time=time(13, 0),
            location_text="CP HP",
            notes="",
            recurrence_rule=None,
            attendees=[],
        )
        aprima = [{
            "id": "apr-1",
            "date": "2026-07-15",
            "title": "Referral Sync",
            "start": "09:00",
            "end": "09:30",
            "serviceSite": "Clermont Office",
            "room": "",
            "reason": "MEETING",
            "surgeonInitials": "CJ",
            "surgeonName": "Chris Johnson",
        }]
        by_day = calendar_events_by_day(
            schedule_days=[day],
            cal_meetings=[cal],
            aprima_meetings=aprima,
        )
        events = by_day["2026-07-15"]
        self.assertEqual(len(events), 2)
        self.assertEqual(events[0]["source"], "aprima")
        self.assertEqual(events[0]["start"], "09:00")
        self.assertEqual(events[1]["source"], "cal")
        self.assertEqual(events[1]["id"], 54)


if __name__ == "__main__":
    unittest.main()
