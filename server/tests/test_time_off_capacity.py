"""Time-off groups: Chris's yellow/red rule for overlapping time off."""

import os
import unittest
from datetime import date, timedelta
from unittest.mock import patch

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("SECRET_KEY", "test-secret")

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.day_off_card_normalization import sync_day_off_card_links
from app.migrate_time_off_groups import seed_time_off_groups
from app.models import (
    AdminNotification,
    AdminUser,
    Base,
    ClinicGroup,
    ClinicGroupMember,
    DayOff,
    ScheduleCard,
    ScheduleCardWeek,
    Surgeon,
)
from app.native_request_off_helpers import NativeRequestOffInput
from app.native_request_off_service import (
    check_native_request_off,
    create_native_request_off,
    update_native_request_off,
)
from app.scheduling_gate_service import build_dayoff_review_findings
from app.time_off_capacity import check_day_off, check_new_request


def _next_weekday(offset_days: int = 21) -> date:
    day = date.today() + timedelta(days=offset_days)
    while day.weekday() >= 5:
        day += timedelta(days=1)
    return day


DAY = _next_weekday()
NAMES = [
    ("Chris", "Johnson"), ("Nadia", "Florin"), ("Alex", "Dean"),
    ("Lucy", "Woodley"), ("Mark", "Schroeder"), ("Paul", "Ivers"),
]


class TimeOffCapacityTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(bind=self.engine)
        with self.engine.begin() as conn:
            seed_time_off_groups(conn)
        self.db = sessionmaker(bind=self.engine)()
        self.docs = []
        for index, (first, last) in enumerate(NAMES, start=1):
            doc = Surgeon(first_name=first, last_name=last, email=f"d{index}@example.com", is_active=True)
            self.db.add(doc)
            self.db.flush()
            week = ScheduleCardWeek(surgeon_id=doc.id, week_start=DAY - timedelta(days=DAY.weekday()), master_revision="t")
            self.db.add(week)
            self.db.flush()
            for session in ("am", "pm"):
                self.db.add(ScheduleCard(
                    week_id=week.id, surgeon_id=doc.id, date=DAY, session=session,
                    baseline_state="na", effective_state="na", source="master",
                ))
            self.docs.append(doc)
        self.db.add(AdminUser(
            username="shannon", email="s@example.com", password_hash="x",
            is_active=True, notify_day_off_requests=True,
        ))
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def _off(self, doc, *, status="approved", reason="Vacation", half=None):
        row = DayOff(surgeon_id=doc.id, start_date=DAY, end_date=DAY, status=status, reason=reason)
        if half == "am":
            row.is_full_day, row.segments = False, f'[{{"date": "{DAY.isoformat()}", "isFullDay": false, "start": "07:00", "end": "11:00"}}]'
        if half == "pm":
            row.is_full_day, row.segments = False, f'[{{"date": "{DAY.isoformat()}", "isFullDay": false, "start": "13:00", "end": "17:00"}}]'
        self.db.add(row)
        self.db.flush()
        sync_day_off_card_links(self.db, row)
        self.db.commit()
        return row

    def _check(self, doc, **kwargs):
        return check_new_request(self.db, doc.id, start_date=DAY, end_date=DAY, **kwargs)

    def test_seed_makes_whole_practice_three_and_four(self):
        whole = self.db.query(ClinicGroup).filter_by(applies_to_all=True).one()
        self.assertEqual((whole.name, whole.yellow_at_off, whole.red_at_off), ("Whole practice", 3, 4))

    def test_seed_carries_old_group_limits(self):
        lm = ClinicGroup(name="Lake Mary", abbreviation="LM", group_type="people",
                         enforce_day_off_limit=True, max_approved_off_per_day=1, is_active=True)
        self.db.add(lm)
        self.db.commit()
        with self.engine.begin() as conn:
            seed_time_off_groups(conn)
            seed_time_off_groups(conn)  # repeat-safe
        self.db.refresh(lm)
        self.assertEqual((lm.yellow_at_off, lm.red_at_off), (2, 3))
        self.assertEqual(self.db.query(ClinicGroup).filter_by(applies_to_all=True).count(), 1)

    def test_chris_rule_clear_yellow_red(self):
        requester = self.docs[5]
        self.assertIsNone(self._check(requester).level)
        self._off(self.docs[0])
        self.assertIsNone(self._check(requester).level)
        self._off(self.docs[1], status="pending")
        result = self._check(requester)
        self.assertEqual(result.level, "yellow")
        self.assertIn("CJ and NF", result.surgeon_message())
        self._off(self.docs[2])
        result = self._check(requester)
        self.assertEqual(result.level, "red")
        self.assertTrue(result.surgeon_message().startswith("Not sent: 4 would be off"))

    def test_no_call_denied_and_other_half_day_do_not_count(self):
        requester = self.docs[5]
        self._off(self.docs[0], reason="No Call")
        self._off(self.docs[1], status="denied")
        self._off(self.docs[2], half="am")
        self._off(self.docs[3], half="am")
        # PM-only request: the two morning-only requests are a different half-day.
        pm = [{"date": DAY.isoformat(), "isFullDay": False, "start": "13:00", "end": "17:00"}]
        self.assertIsNone(self._check(requester, is_full_day=False, segments=pm).level)
        # Full day overlaps the morning: CJ's No Call and NF's denied still do not count.
        self.assertEqual(self._check(requester).level, "yellow")

    def test_member_group_uses_its_own_numbers(self):
        lm = ClinicGroup(name="Lake Mary", abbreviation="LM", group_type="people",
                         yellow_at_off=2, red_at_off=3, is_active=True)
        self.db.add(lm)
        self.db.flush()
        for doc in self.docs[:3]:
            self.db.add(ClinicGroupMember(clinic_group_id=lm.id, surgeon_id=doc.id))
        self.db.commit()
        self._off(self.docs[0])
        result = self._check(self.docs[1])
        self.assertEqual(result.level, "yellow")
        self.assertIn("Lake Mary", result.surgeon_message())
        # Not a Lake Mary member: only Whole practice applies, 2 off is clear.
        self.assertIsNone(self._check(self.docs[4]).level)
        self._off(self.docs[1])
        self.assertEqual(self._check(self.docs[2]).level, "red")

    def test_saved_request_review_excludes_itself_and_shows_color(self):
        for doc in self.docs[:3]:
            self._off(doc, status="pending")
        mine = self._off(self.docs[3], status="pending")
        self.assertEqual(check_day_off(self.db, mine).level, "red")
        findings = build_dayoff_review_findings(self.db, mine)
        self.assertEqual(findings[0].severity, "red")
        self.assertEqual(findings[0].kind, "time_off_capacity")

    def _payload(self, **kwargs):
        return NativeRequestOffInput(start_date=DAY, end_date=DAY, reason="Vacation", **kwargs)

    @patch("app.native_request_off_service.send_time_off_request_copy", return_value=False)
    @patch("app.native_request_off_service.send_native_push_to_surgeon")
    @patch("app.push.send_sms")
    def test_red_iphone_request_is_not_saved_and_alerts_shannon(self, sms, push, email):
        for doc in self.docs[:3]:
            self._off(doc)
        before = self.db.query(DayOff).count()
        preview = check_native_request_off(self.db, self.docs[5], self._payload())
        self.assertEqual(preview["level"], "red")
        self.assertEqual(self.db.query(AdminNotification).count(), 0)

        result = create_native_request_off(self.db, self.docs[5], self._payload())
        self.assertFalse(result["ok"])
        self.assertIn("Please talk with", result["warnings"][0])
        self.assertEqual(self.db.query(DayOff).count(), before)
        alert = self.db.query(AdminNotification).one()
        self.assertEqual((alert.kind, alert.title), ("time_off_red", "Red alert: time off"))
        push.assert_not_called()

    @patch("app.native_request_off_service.send_time_off_request_copy", return_value=False)
    @patch("app.native_request_off_service.send_native_push_to_surgeon")
    def test_yellow_iphone_request_is_saved_and_marked(self, push, email):
        self._off(self.docs[0])
        self._off(self.docs[1])
        result = create_native_request_off(self.db, self.docs[5], self._payload())
        self.assertTrue(result["ok"])
        self.assertTrue(any("Heads up" in w for w in result["warnings"]))
        notice = self.db.query(AdminNotification).one()
        self.assertEqual(notice.title, "Pending Request (yellow)")

    @patch("app.native_request_off_service.send_time_off_request_copy", return_value=False)
    @patch("app.native_request_off_service.send_native_push_to_surgeon")
    @patch("app.push.send_sms")
    def test_red_edit_leaves_the_old_request_unchanged(self, sms, push, email):
        for doc in self.docs[:3]:
            self._off(doc)
        other_day = _next_weekday(40)
        mine = DayOff(surgeon_id=self.docs[5].id, start_date=other_day, end_date=other_day,
                      status="pending", reason="Vacation")
        self.db.add(mine)
        self.db.commit()
        result = update_native_request_off(self.db, self.docs[5], mine.id, self._payload())
        self.assertFalse(result["ok"])
        self.db.refresh(mine)
        self.assertEqual(mine.start_date, other_day)


if __name__ == "__main__":
    unittest.main()
