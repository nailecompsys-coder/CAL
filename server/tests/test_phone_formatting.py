import os
import unittest

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("SECRET_KEY", "test-secret")

from app.admin_surgeon_service import format_us_phone


class PhoneFormattingTest(unittest.TestCase):
    def test_service_formats_us_phone_for_storage(self):
        self.assertEqual(format_us_phone("4075550100"), "(407) 555-0100")
        self.assertEqual(format_us_phone("+1 (407) 555-0100"), "(407) 555-0100")
        self.assertEqual(format_us_phone("555"), "555")
        self.assertEqual(format_us_phone(""), "")


if __name__ == "__main__":
    unittest.main()
