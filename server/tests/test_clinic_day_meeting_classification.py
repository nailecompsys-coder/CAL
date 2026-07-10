import os
import unittest
from types import SimpleNamespace

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("SECRET_KEY", "test-secret")

from app.native_home_serializers import (
    is_clinic_day_meeting,
    is_clinic_rotation_text,
    meeting_item_payload,
)


class ClinicDayMeetingClassificationTest(unittest.TestCase):
    def test_surgery_one_clinic_cbo_is_clinic_not_meeting(self):
        meeting = SimpleNamespace(
            id=64,
            title="CJ Surgery 1 Clinic",
            location_text="CBO",
            start_time=None,
            end_time=None,
            notes="",
        )
        # Avoid needing real time objects in fmt_time by patching via payload fields after
        meeting.start_time = __import__("datetime").time(8, 30)
        meeting.end_time = __import__("datetime").time(11, 0)

        self.assertTrue(is_clinic_day_meeting(meeting))
        payload = meeting_item_payload(meeting)
        self.assertEqual(payload["type"], "clinic")
        self.assertIn("Surgery 1 Clinic", payload["title"])
        self.assertIn("CBO", payload["title"])
        self.assertEqual(payload["subtitle"], "CLINIC")

    def test_surgical_one_clinic_label_is_clinic_rotation(self):
        self.assertTrue(
            is_clinic_rotation_text(title="Surgical One Clinic", location="CBO")
        )
        self.assertTrue(
            is_clinic_rotation_text(title="Surgical One", location="", reason="")
        )

    def test_meeting_at_wg_clinic_location_stays_meeting(self):
        meeting = SimpleNamespace(
            id=68,
            title="JF-Dr. Hill Meeting",
            location_text="WG Clinic",
            start_time=__import__("datetime").time(10, 0),
            end_time=__import__("datetime").time(10, 30),
            notes="",
        )
        self.assertFalse(is_clinic_day_meeting(meeting))

    def test_real_teams_meeting_stays_meeting(self):
        meeting = SimpleNamespace(
            id=70,
            title="JF-Teams Meeting",
            location_text="Teams",
            start_time=__import__("datetime").time(10, 0),
            end_time=__import__("datetime").time(10, 30),
            notes="",
        )
        self.assertFalse(is_clinic_day_meeting(meeting))
        payload = meeting_item_payload(meeting)
        self.assertEqual(payload["type"], "meeting")

    def test_cancelled_clinic_day_is_not_reclassified(self):
        meeting = SimpleNamespace(
            id=66,
            title="CANCEL-OUT OF TOWN Surgery 1 Clinic",
            location_text="CBO",
            start_time=None,
            end_time=None,
            notes="",
        )
        self.assertFalse(is_clinic_day_meeting(meeting))


if __name__ == "__main__":
    unittest.main()
