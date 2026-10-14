import os
import unittest
from datetime import time
from types import SimpleNamespace

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("SECRET_KEY", "test-secret")

from app.native_home_serializers import meeting_item_payload


class MeetingPayloadNoClassificationTest(unittest.TestCase):
    """CAL meetings-table rows stay type=meeting — no Python title rewrite to clinic."""

    def test_surgery_one_clinic_reminder_stays_meeting(self):
        meeting = SimpleNamespace(
            id=64,
            title="CJ Surgery 1 Clinic",
            location_text="CBO",
            start_time=time(8, 30),
            end_time=time(11, 0),
            notes="",
        )
        payload = meeting_item_payload(meeting)
        self.assertEqual(payload["type"], "meeting")
        self.assertEqual(payload["title"], "CJ Surgery 1 Clinic")
        self.assertEqual(payload["subtitle"], "CBO")
        self.assertTrue(payload["id"].startswith("mtg-"))

    def test_surgery_one_board_meeting_stays_meeting(self):
        meeting = SimpleNamespace(
            id=72,
            title="Surgery One Board Meeting",
            location_text="1814 Lucerne Terrace Orlando, FL",
            start_time=time(17, 0),
            end_time=time(18, 0),
            notes="",
        )
        payload = meeting_item_payload(meeting)
        self.assertEqual(payload["type"], "meeting")
        self.assertEqual(payload["title"], "Surgery One Board Meeting")
        self.assertIn("Lucerne", payload["subtitle"])

    def test_teams_meeting_stays_meeting(self):
        meeting = SimpleNamespace(
            id=70,
            title="JF-Teams Meeting",
            location_text="Teams",
            start_time=time(10, 0),
            end_time=time(10, 30),
            notes="",
        )
        payload = meeting_item_payload(meeting)
        self.assertEqual(payload["type"], "meeting")


if __name__ == "__main__":
    unittest.main()
