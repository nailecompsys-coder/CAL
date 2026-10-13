import os
import unittest

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

from app.models import Surgeon
from app.push import resolve_push_sound


class PushSoundResolveTest(unittest.TestCase):
    def test_default_sound(self):
        self.assertEqual(resolve_push_sound(None), "cal_alert.wav")

    def test_surgeon_custom_sound(self):
        cj = Surgeon(first_name="Christopher", last_name="Johnson", push_sound="bagpipes.wav")
        self.assertEqual(resolve_push_sound(cj), "bagpipes.wav")

    def test_override_wins(self):
        cj = Surgeon(first_name="Christopher", last_name="Johnson", push_sound="bagpipes.wav")
        self.assertEqual(resolve_push_sound(cj, "cal_alert.wav"), "cal_alert.wav")

    def test_rejects_unsafe_filename(self):
        sneaky = Surgeon(first_name="X", last_name="Y", push_sound="../etc/passwd")
        self.assertEqual(resolve_push_sound(sneaky), "cal_alert.wav")


if __name__ == "__main__":
    unittest.main()
