"""Admin notification cards must open the record that needs fixing."""

import os
import unittest
from datetime import date
from unittest.mock import patch

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("SECRET_KEY", "test-secret")

from app.admin_notification_href import admin_notification_href, clinic_schedule_fix_href


class AdminNotificationHrefTest(unittest.TestCase):
    def test_day_off_request_opens_that_pending_row(self):
        href = admin_notification_href("day_off_request", {
            "dayOffId": 44,
            "startDate": "2026-09-01",
            "endDate": "2026-09-04",
        })
        self.assertIn("/admin/daysoff?focus=44", href)
        self.assertIn("gantt_start=2026-09-01", href)
        self.assertIn("gantt_end=2026-09-04", href)

    def test_day_off_duplicate_opens_the_kept_request(self):
        href = admin_notification_href("day_off_duplicate", {"keptId": 12, "deletedId": 13})
        self.assertEqual(href, "/admin/daysoff?focus=12")

    def test_schedule_flag_opens_that_block_or_card(self):
        with patch("app.admin_notification_href.week_offset_for_date", return_value=3):
            href = admin_notification_href("schedule_flag", {
                "blockId": 88,
                "date": "2026-09-10",
                "href": "/admin/scheduler-availability",
            })
        self.assertIn("/admin/block-or?", href)
        self.assertIn("block_id=88", href)
        self.assertIn("week_offset=3", href)
        self.assertIn("panel=assign", href)
        self.assertNotIn("scheduler-availability", href)

    def test_missing_time_opens_add_case_for_that_surgeon_day(self):
        with patch("app.admin_notification_href.week_offset_for_date", return_value=2):
            href = admin_notification_href("ingest_correction", {
                "reason": "missing_time",
                "surgeonId": 7,
                "date": "2026-08-20",
                "patientName": "Mercer, Kurt",
                "procedure": "OPEN UMBILICAL HERNIA REPAIR",
                "href": "/admin/clinic-schedule",
            })
        self.assertIn("/admin/clinic-schedule?", href)
        self.assertIn("surgeon_id=7", href)
        self.assertIn("focus_date=2026-08-20", href)
        self.assertIn("fix=missing_time", href)
        self.assertIn("patient=", href)
        self.assertIn("week_offset=2", href)

    def test_clinic_location_opens_that_cell_not_locations_admin(self):
        with patch("app.admin_notification_href.week_offset_for_date", return_value=0):
            href = admin_notification_href("ingest_correction", {
                "reason": "clinic_location_not_found",
                "surgeonId": 7,
                "date": "2026-08-17",
                "site": "NO_SUCH_SITE",
                "href": "/admin/locations",
            })
        self.assertIn("/admin/clinic-schedule?", href)
        self.assertIn("fix=clinic_location", href)
        self.assertIn("surgeon_id=7", href)
        self.assertIn("focus_date=2026-08-17", href)
        self.assertIn("site=NO_SUCH_SITE", href)
        self.assertNotIn("/admin/locations", href)

    def test_or_location_opens_clinic_cell_not_locations_admin(self):
        href = admin_notification_href("ingest_correction", {
            "reason": "or_location_not_found",
            "surgeonId": 3,
            "date": "2026-08-21",
            "extra": "APK S99",
            "href": "/admin/locations",
        })
        self.assertIn("fix=or_location", href)
        self.assertIn("room=APK", href)
        self.assertNotIn("/admin/locations", href)

    def test_unknown_surgeon_opens_add_physician_with_fax_name(self):
        href = admin_notification_href("ingest_correction", {
            "reason": "surgeon_not_found",
            "extra": "New Surgeon, MD",
            "href": "/admin/surgeons",
        })
        self.assertIn("/admin/surgeons?", href)
        self.assertIn("add=1", href)
        self.assertIn("name=", href)

    def test_call_coverage_opens_that_rotation(self):
        href = admin_notification_href("call_coverage_conflict", {
            "rotationId": 19,
            "date": date(2026, 10, 2),
            "coveringSurgeonId": 4,
        })
        self.assertIn("/admin/call-schedule?", href)
        self.assertIn("rotation_id=19", href)
        self.assertIn("month_offset=", href)

    def test_rules_engine_error_scrolls_to_that_rule(self):
        href = admin_notification_href("rules_engine_error", {"ruleId": "OVERLAP_CALL"})
        self.assertEqual(href, "/admin/settings/scheduling-rules#rule-OVERLAP_CALL")

    def test_clinic_schedule_fix_href_includes_edit_case(self):
        with patch("app.admin_notification_href.week_offset_for_date", return_value=1):
            href = clinic_schedule_fix_href(
                day=date(2026, 8, 20),
                surgeon_id=7,
                case_id=55,
                reason="missing_time",
            )
        self.assertIn("edit_case=55", href)
        self.assertIn("fix=missing_time", href)


if __name__ == "__main__":
    unittest.main()
