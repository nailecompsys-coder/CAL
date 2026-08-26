"""Practice-local calendar day must stay Eastern after UTC has rolled."""

import os
import unittest
from datetime import date, datetime, timezone
from unittest.mock import patch

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

from app.practice_time import PRACTICE_TZ, practice_today


class _FrozenDateTime(datetime):
    @classmethod
    def now(cls, tz=None):
        instant = datetime(2026, 8, 26, 0, 21, tzinfo=timezone.utc)
        return instant.astimezone(tz) if tz else instant.replace(tzinfo=None)


class PracticeTimeTest(unittest.TestCase):
    def test_practice_today_stays_eastern_when_utc_has_rolled(self):
        with patch("app.practice_time.datetime", _FrozenDateTime):
            self.assertEqual(practice_today(), date(2026, 8, 25))

    def test_practice_tz_is_new_york(self):
        self.assertEqual(str(PRACTICE_TZ), "America/New_York")
