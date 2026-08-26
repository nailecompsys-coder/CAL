"""Fax-group date rules: DOBs stay off the OR board; OCR years snap into the week."""
import os
import unittest
from datetime import date

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("SECRET_KEY", "test-secret")

from app.ingest_date_rules import (
    date_allowed_for_fax,
    infer_fax_group_window,
    looks_like_patient_dob,
    plausible_schedule_date,
    snap_date_into_fax_window,
)


class IngestDateRulesTest(unittest.TestCase):
    def setUp(self):
        self.today = date(2026, 8, 26)
        self.payload = [{
            "start_date": "2026-08-24",
            "end_date": "2026-08-28",
            "or_block": {
                "cases": [
                    {"case_date": "2026-08-25", "patient_name": "Dhanessur, Shirley"},
                    {"case_date": "1965-07-27", "patient_name": "Wilkinson, Llyod"},
                    {"case_date": "2028-08-27", "patient_name": "Ferber, Robert"},
                ]
            },
        }]

    def test_fax_window_ignores_dob_and_ocr_years(self):
        window = infer_fax_group_window(self.payload, today=self.today)
        self.assertEqual(window, (date(2026, 8, 24), date(2026, 8, 28)))

    def test_wilkinson_dob_is_rejected(self):
        window = infer_fax_group_window(self.payload, today=self.today)
        self.assertIsNone(date_allowed_for_fax(date(1965, 7, 27), window, today=self.today))
        self.assertFalse(plausible_schedule_date(date(1965, 7, 27), self.today))
        self.assertTrue(looks_like_patient_dob(date(1965, 7, 27), window, today=self.today))
        self.assertFalse(looks_like_patient_dob(date(2028, 8, 27), window, today=self.today))

    def test_forty_years_before_fax_week_is_dob(self):
        window = (date(2026, 8, 24), date(2026, 8, 28))
        self.assertTrue(looks_like_patient_dob(date(1952, 7, 8), window, today=self.today))
        self.assertTrue(looks_like_patient_dob(date(2006, 3, 17), window, today=self.today))
        self.assertFalse(looks_like_patient_dob(date(2026, 8, 25), window, today=self.today))
        self.assertIsNone(date_allowed_for_fax(date(1952, 7, 8), window, today=self.today))

    def test_ocr_year_snaps_into_fax_week(self):
        window = infer_fax_group_window(self.payload, today=self.today)
        self.assertEqual(
            snap_date_into_fax_window(date(2028, 8, 27), window, today=self.today),
            date(2026, 8, 27),
        )
        self.assertEqual(
            date_allowed_for_fax(date(2028, 8, 27), window, today=self.today),
            date(2026, 8, 27),
        )

    def test_real_case_date_stays(self):
        window = infer_fax_group_window(self.payload, today=self.today)
        self.assertEqual(
            date_allowed_for_fax(date(2026, 8, 25), window, today=self.today),
            date(2026, 8, 25),
        )


if __name__ == "__main__":
    unittest.main()
