import unittest

from app.version_display import release_channel, release_label


class VersionDisplayTest(unittest.TestCase):
    def test_release_label_uses_compact_portal_format(self):
        self.assertEqual(release_label("1.3.5-beta.1+20260615T224639Z"), "1.35")
        self.assertEqual(release_label("2.0.1"), "2.01")

    def test_release_channel_detects_beta(self):
        self.assertEqual(release_channel("1.3.5-beta.1+20260615T224639Z"), "BETA")
        self.assertEqual(release_channel("1.3.5"), "")


if __name__ == "__main__":
    unittest.main()
