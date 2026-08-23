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
        self.assertIn("Shannon", DUPLICATE_REJECT_MESSAGE)
        self.assertIn("overlap", DUPLICATE_REJECT_MESSAGE.lower())


class DuplicateGateStatusTest(unittest.TestCase):
    def test_reject_never_raises_http(self):
        from app.scheduling_gate_service import reject_if_duplicate_day_off
        import inspect
        src = inspect.getsource(reject_if_duplicate_day_off)
        self.assertIn("never hard-block", src)
        self.assertNotIn("raise HTTPException", src)

    def test_overlap_advisory_mentions_shannon(self):
        from app.scheduling_gate_service import OVERLAP_ADVISORY_MESSAGE
        self.assertIn("Shannon", OVERLAP_ADVISORY_MESSAGE)


class CallCoverageOverlapTest(unittest.TestCase):
    def test_covering_surgeon_is_flagged_not_original(self):
        from app.rules_engine.overlap_checkers import check_overlap_call

        day = date.today() + timedelta(days=10)
        coverage = SimpleNamespace(id=9, status="active", covering_surgeon_id=22)
        rotation = SimpleNamespace(
            id=1,
            surgeon_id=16,
            date=day,
            call_group_id=1,
            call_group=SimpleNamespace(name="Winter Garden"),
            coverages=[coverage],
        )
        db = MagicMock()

        def query_any(*args, **kwargs):
            query = MagicMock()
            query.options.return_value = query
            query.filter.return_value = query
            # First call is CallRotation; later CallGroupLocation
            if not hasattr(query_any, "n"):
                query_any.n = 0
            query_any.n += 1
            if query_any.n == 1:
                query.all.return_value = [rotation]
            else:
                query.all.return_value = []
            return query

        db.query.side_effect = query_any

        covering = list(check_overlap_call(22, day, day, db, {}, None, {"type": "day_off", "start_date": day, "end_date": day, "is_full_day": True, "segments": []}))
        query_any.n = 0
        original = list(check_overlap_call(16, day, day, db, {}, None, {"type": "day_off", "start_date": day, "end_date": day, "is_full_day": True, "segments": []}))
        self.assertEqual(len(covering), 1)
        self.assertIn("Covering on-call", covering[0].message)
        self.assertEqual(original, [])

    def test_on_call_never_conflicts_with_or_block(self):
        """On call + a Block OR is fine at any hospital; day-off still conflicts."""
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker

        from app.models import (
            Base,
            CallGroup,
            CallGroupLocation,
            CallRotation,
            Location,
            ORBlockAssignment,
            ORBlockInstance,
            Surgeon,
        )
        from app.rules_engine.overlap_checkers import check_overlap_call, check_overlap_or_block

        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        db = sessionmaker(bind=engine)()
        try:
            day = date(2026, 7, 29)
            surgeon = Surgeon(
                first_name="Alex",
                last_name="Schroeder",
                email="alex@example.com",
                is_active=True,
                staff_type="physician",
            )
            ap = Location(name="Apopka OR", abbreviation="AP-OR", location_type="hospital", is_active=True)
            al = Location(name="Altamonte OR", abbreviation="AL-OR", location_type="hospital", is_active=True)
            group = CallGroup(name="Winter Garden / Apopka / Minneola Hospital")
            db.add_all([surgeon, ap, al, group])
            db.flush()
            db.add_all([
                CallGroupLocation(call_group_id=group.id, location_id=ap.id),
                CallRotation(surgeon_id=surgeon.id, call_group_id=group.id, date=day),
            ])
            db.commit()

            same = list(
                check_overlap_call(
                    surgeon.id,
                    day,
                    day,
                    db,
                    {},
                    None,
                    {
                        "type": "or_block",
                        "date": day,
                        "start_time": time(7, 15),
                        "end_time": time(10, 15),
                        "location_id": ap.id,
                    },
                )
            )
            other = list(
                check_overlap_call(
                    surgeon.id,
                    day,
                    day,
                    db,
                    {},
                    None,
                    {
                        "type": "or_block",
                        "date": day,
                        "start_time": time(7, 15),
                        "end_time": time(10, 15),
                        "location_id": al.id,
                    },
                )
            )
            day_off = list(
                check_overlap_call(
                    surgeon.id,
                    day,
                    day,
                    db,
                    {},
                    None,
                    {"type": "day_off", "start_date": day, "end_date": day, "is_full_day": True, "segments": []},
                )
            )
            block = ORBlockInstance(
                location_id=al.id,
                date=day,
                session="am",
                start_time=time(7, 15),
                end_time=time(10, 15),
                status="assigned",
            )
            db.add(block)
            db.flush()
            db.add(ORBlockAssignment(
                block_instance_id=block.id,
                surgeon_id=surgeon.id,
                start_time=time(7, 15),
            ))
            db.commit()
            assign_call = list(
                check_overlap_or_block(
                    surgeon.id,
                    day,
                    day,
                    db,
                    {},
                    None,
                    {"type": "call_rotation", "date": day},
                )
            )
            # Block OR at the on-call hospital OR a different hospital: both fine.
            self.assertEqual(same, [])
            self.assertEqual(other, [])
            # Assigning call when they already have a block at another hospital: also fine.
            self.assertEqual(assign_call, [])
            # Day off while on call is still a real conflict worth surfacing.
            self.assertEqual(len(day_off), 1)
        finally:
            db.close()
            engine.dispose()


if __name__ == "__main__":
    unittest.main()
