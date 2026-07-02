import unittest
from unittest.mock import Mock, patch

from app.sms_service import generate_sms_otp


class SmsServiceTest(unittest.TestCase):
    def test_generate_sms_otp_uses_textbelt_otp_endpoint(self):
        response = Mock()
        response.json.return_value = {"success": True, "otp": "672383", "quotaRemaining": 70}

        with patch("app.sms_service.requests.post", return_value=response) as post:
            success, otp, failure = generate_sms_otp(
                phone="(407) 555-1212",
                userid="cal:surgeon:42",
                message="CAL access code: $OTP",
                lifetime=900,
                length=6,
            )

        self.assertTrue(success)
        self.assertEqual(otp, "672383")
        self.assertIsNone(failure)
        post.assert_called_once()
        url = post.call_args.args[0]
        payload = post.call_args.kwargs["data"]
        self.assertEqual(url, "https://textbelt.com/otp/generate")
        self.assertEqual(payload["phone"], "4075551212")
        self.assertEqual(payload["userid"], "cal:surgeon:42")
        self.assertEqual(payload["message"], "CAL access code: $OTP")
        self.assertEqual(payload["lifetime"], 900)
        self.assertEqual(payload["length"], 6)

    def test_generate_sms_otp_rejects_blank_phone(self):
        success, otp, failure = generate_sms_otp(
            phone="",
            userid="cal:surgeon:42",
            message="CAL access code: $OTP",
            lifetime=900,
        )

        self.assertFalse(success)
        self.assertIsNone(otp)
        self.assertEqual(failure, "Invalid phone number.")


if __name__ == "__main__":
    unittest.main()
