import unittest

from app.device_names import readable_device_name


class DeviceNamesTest(unittest.TestCase):
    def test_native_ios_user_agent_is_readable(self):
        self.assertEqual(
            readable_device_name("CALNative/11 CFNetwork/3860.500.112 Darwin/25.4.0"),
            "CAL iPhone app",
        )

    def test_android_user_agent_is_readable(self):
        self.assertEqual(readable_device_name("okhttp/4.9.2"), "Android app")

    def test_browser_user_agent_is_readable(self):
        self.assertEqual(
            readable_device_name(None, "Mozilla/5.0 (iPhone; CPU iPhone OS 18_7 like Mac OS X)"),
            "iPhone browser",
        )

    def test_admin_preview_is_readable(self):
        self.assertEqual(readable_device_name("Admin desktop preview"), "Admin preview")


if __name__ == "__main__":
    unittest.main()
