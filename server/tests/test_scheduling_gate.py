"""Tests for scheduling gate + time-aware / call-coverage rules."""
import os
import unittest
from datetime import date, datetime, time, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

from app.rules_engine.checker_helpers import day_off_unavailable_range_on_day
from app.rules_engine.overlap_helpers import OverlapTarget, should_skip_time_overlap
from app.scheduling_gate_service import (
    DUPLICATE_REJECT_MESSAGE,
    clip_window_to_now,
    day_off_target_entity,
    surgeon_friendly_conflict_message,
)
from app.scheduling_guardrails_service import DayOffFinding


class SchedulingGateHelpersTest(unittest.TestCase):
    def test_clip_window_drops_fully_past(self):
        today = date.today()
        self.assertIsNone(clip_window_to_now(today - timedelta(days=5), today - timedelta(days=1)))

    def test_clip_window_trims_start_to_today(self):
        today = date.today()
        clipped = clip_window_to_now(today - timedelta(days=3), today + timedelta(days=2))
        self.assertEqual(clipped, (today, today + timedelta(days=2)))

    def test_partial_day_unavailable_range(self):
        day = date(2026, 8, 1)
        entity = day_off_target_entity(
            start_date=day,
            end_date=day,
            is_full_day=False,
            start_time=time(8, 0),
            end_time=time(13, 0),
            segments=[{
                "date": day.isoformat(),
                "isFullDay": False,
                "start": "08:00",
                "end": "13:00",
            }],
        )
        off = day_off_unavailable_range_on_day(entity, day)
        self.assertEqual(off[0].time(), time(8, 0))
        self.assertEqual(off[1].time(), time(13, 0))

    def test_partial_day_skips_afternoon_clinic(self):
        day = date(2026, 8, 1)
        entity = day_off_target_entity(
            start_date=day,
            end_date=day,
            is_full_day=False,
            segments=[{
                "date": day.isoformat(),
                "isFullDay": False,
                "start": "08:00",
                "end": "13:00",
            }],
        )
        target = OverlapTarget(
            kind="day_off",
            start=day,
            end=day,
            day=None,
            range=None,
            entity=entity,
        )
        pm_clinic = (
            datetime.combine(day, time(13, 0)),
            datetime.combine(day, time(17, 0)),
        )
        am_clinic = (
            datetime.combine(day, time(8, 0)),
            datetime.combine(day, time(12, 0)),
        )
        self.assertTrue(should_skip_time_overlap(target, day, pm_clinic, set()))
        self.assertFalse(should_skip_time_overlap(target, day, am_clinic, set()))

    def test_friendly_message_mentions_shannon(self):
        findings = [
            DayOffFinding(
                severity="warning",
                kind="clinic_schedule",
                date=date(2026, 7, 17),
                message="Clinic at Minneola OR on Jul 17 (am)",
                surgeon_message="Clinic at Minneola OR on Jul 17 (am).",
            )
        ]
        msg = surgeon_friendly_conflict_message(findings)
        self.assertIn("Shannon", msg)
        self.assertIn("Clinic at Minneola", msg)

    def test_duplicate_message_is_clear(self):
        self.assertIn("Duplicates are not allowed", DUPLICATE_REJECT_MESSAGE)


class CallCoverageOverlapTest(unittest.TestCase):
    def test_covering_surgeon_is_flagged_not_original(self):
        from app.rules_engine.overlap_checkers import check_overlap_call

        day = date.today() + timedelta(days=10)
        coverage = SimpleNamespace(id=9, status="active", covering_surgeon_id=22)
        rotation = SimpleNamespace(
            id=1,
            surgeon_id=16,
            date=day,
            call_group=SimpleNamespace(name="Winter Garden"),
            coverages=[coverage],
        )
        db = MagicMock()
        query = MagicMock()
        db.query.return_value = query
        query.options.return_value = query
        query.filter.return_value = query
        query.all.return_value = [rotation]

        covering = list(check_overlap_call(22, day, day, db, {}, None, {"type": "day_off", "start_date": day, "end_date": day, "is_full_day": True, "segments": []}))
        original = list(check_overlap_call(16, day, day, db, {}, None, {"type": "day_off", "start_date": day, "end_date": day, "is_full_day": True, "segments": []}))
        self.assertEqual(len(covering), 1)
        self.assertIn("Covering on-call", covering[0].message)
        self.assertEqual(original, [])


if __name__ == "__main__":
    unittest.main()
