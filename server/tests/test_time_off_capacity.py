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
        # Chris: counted by group. WG holds all six doctors at 2 yellow / 3 red.
        self.wg = ClinicGroup(name="Winter Garden", abbreviation="WG", group_type="people",
                              yellow_at_off=2, red_at_off=3, is_active=True)
        self.db.add(self.wg)
        self.db.flush()
        for doc in self.docs:
            self.db.add(ClinicGroupMember(clinic_group_id=self.wg.id, surgeon_id=doc.id))
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

    def test_seed_adds_whole_practice_turned_off(self):
        whole = self.db.query(ClinicGroup).filter_by(applies_to_all=True).one()
        self.assertEqual((whole.name, whole.is_active, whole.yellow_at_off, whole.red_at_off),
                         ("Whole practice", False, 2, 3))

    def test_seed_turns_off_first_release_whole_practice(self):
        whole = self.db.query(ClinicGroup).filter_by(applies_to_all=True).one()
        whole.is_active, whole.yellow_at_off, whole.red_at_off = True, 3, 4
        self.db.commit()
        with self.engine.begin() as conn:
            seed_time_off_groups(conn)
        self.db.refresh(whole)
        self.assertEqual((whole.is_active, whole.yellow_at_off, whole.red_at_off), (False, 2, 3))
        # Turned back on by Shannon at 2/3, it stays on.
        whole.is_active = True
        self.db.commit()
        with self.engine.begin() as conn:
            seed_time_off_groups(conn)
        self.db.refresh(whole)
        self.assertTrue(whole.is_active)

    def test_seed_moves_old_switch_groups_to_two_and_three_once(self):
        lm = ClinicGroup(name="Lake Mary", abbreviation="LM", group_type="people",
                         enforce_day_off_limit=True, max_approved_off_per_day=1, is_active=True)
        self.db.add(lm)
        self.db.commit()
        with self.engine.begin() as conn:
            seed_time_off_groups(conn)
        self.db.refresh(lm)
        self.assertEqual((lm.yellow_at_off, lm.red_at_off, lm.enforce_day_off_limit), (2, 3, False))
        lm.yellow_at_off, lm.red_at_off = 4, 5  # Shannon's later choice stays put
        self.db.commit()
        with self.engine.begin() as conn:
            seed_time_off_groups(conn)
        self.db.refresh(lm)
        self.assertEqual((lm.yellow_at_off, lm.red_at_off), (4, 5))
        self.assertEqual(self.db.query(ClinicGroup).filter_by(applies_to_all=True).count(), 1)

    def test_chris_rule_clear_yellow_red(self):
        requester = self.docs[5]
        self.assertIsNone(self._check(requester).level)
        self._off(self.docs[0], status="pending")
        result = self._check(requester)
        self.assertEqual(result.level, "yellow")
        self.assertIn("CJ is already off", result.surgeon_message())
        self._off(self.docs[1])
        result = self._check(requester)
        self.assertEqual(result.level, "red")
        self.assertTrue(result.surgeon_message().startswith("Red alert: you would make 3 off"))
        people = {p["initials"]: p["status"] for p in result.off_list()}
        self.assertEqual(people, {"CJ": "pending", "NF": "approved"})

    def test_no_call_denied_and_other_half_day_do_not_count(self):
        requester = self.docs[5]
        self._off(self.docs[0], reason="No Call")
        self._off(self.docs[1], status="denied")
        self._off(self.docs[2], half="am")
        self._off(self.docs[3], half="am")
        # PM-only request: the two morning-only requests are a different half-day.
        pm = [{"date": DAY.isoformat(), "isFullDay": False, "start": "13:00", "end": "17:00"}]
        self.assertIsNone(self._check(requester, is_full_day=False, segments=pm).level)
        # Full day overlaps the morning (AD and LW): 3 off. No Call and denied never count.
        result = self._check(requester)
        self.assertEqual(result.level, "red")
        self.assertEqual({p["initials"] for p in result.off_list()}, {"AD", "LW"})

    def test_dons_example_lines_up_each_day(self):
        # A off Dec 2-5 (here DAY..DAY+3), B off the last two days, C asks DAY+1..DAY+3.
        days = [DAY + timedelta(days=i) for i in range(6)]
        days = [d for d in days if d.weekday() < 5][:4]
        for doc in self.docs[:3]:
            week = ScheduleCardWeek(surgeon_id=doc.id, week_start=days[-1] - timedelta(days=days[-1].weekday()), master_revision="t2")
            self.db.add(week)
            self.db.flush()
            for d in days[1:]:
                for session in ("am", "pm"):
                    if not self.db.query(ScheduleCard).filter_by(surgeon_id=doc.id, date=d, session=session).first():
                        self.db.add(ScheduleCard(week_id=week.id, surgeon_id=doc.id, date=d, session=session,
                                                 baseline_state="na", effective_state="na", source="master"))
        self.db.commit()
        for doc, first in ((self.docs[0], days[0]), (self.docs[1], days[2])):
            row = DayOff(surgeon_id=doc.id, start_date=first, end_date=days[3], status="approved", reason="Vacation")
            self.db.add(row)
            self.db.flush()
            sync_day_off_card_links(self.db, row)
        self.db.commit()
        result = check_new_request(self.db, self.docs[2].id, start_date=days[1], end_date=days[3])
        lines = [(line["date"], line["level"], line["offCount"]) for line in result.day_lines()]
        self.assertEqual(lines, [
            (days[1].isoformat(), "yellow", 2),
            (days[2].isoformat(), "red", 3),
            (days[3].isoformat(), "red", 3),
        ])

    def test_exempt_surgeon_gets_no_color_and_never_counts(self):
        cj = self.docs[0]
        cj.time_off_exempt = True
        self.db.commit()
        self._off(self.docs[1])
        self._off(self.docs[2])
        # CJ's own request: no color even with two others off.
        self.assertIsNone(self._check(cj).level)
        # CJ off does not count toward anyone else's.
        self._off(cj)
        result = self._check(self.docs[5])
        self.assertEqual(result.level, "red")
        self.assertEqual({p["initials"] for p in result.off_list()}, {"NF", "AD"})

    def test_member_group_uses_its_own_numbers(self):
        lm = ClinicGroup(name="Lake Mary", abbreviation="LM", group_type="people",
                         yellow_at_off=2, red_at_off=3, is_active=True)
        self.db.add(lm)
        self.db.flush()
        for doc in self.docs[:3]:
            self.db.add(ClinicGroupMember(clinic_group_id=lm.id, surgeon_id=doc.id))
        self.db.commit()
        self.wg.is_active = False
        self.db.commit()
        self._off(self.docs[0])
        result = self._check(self.docs[1])
        self.assertEqual(result.level, "yellow")
        self.assertEqual({h.group_name for h in result.hits}, {"Lake Mary"})
        # Not a Lake Mary member (WG and Whole practice are off): clear.
        self.assertIsNone(self._check(self.docs[4]).level)
        self._off(self.docs[1])
        self.assertEqual(self._check(self.docs[2]).level, "red")

    def test_saved_request_review_excludes_itself_and_shows_color(self):
        for doc in self.docs[:2]:
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
    def test_red_is_never_blocked_saves_and_alerts_shannon(self, sms, push, email):
        for doc in self.docs[:2]:
            self._off(doc)
        before = self.db.query(DayOff).count()
        preview = check_native_request_off(self.db, self.docs[5], self._payload(), show_choice=True)
        self.assertEqual(preview["level"], "red")
        self.assertEqual([p["initials"] for p in preview["offList"]], ["CJ", "NF"])
        self.assertEqual(self.db.query(AdminNotification).count(), 0)
        # Build 31 locks Submit on "red"; older clients get the same message as yellow.
        self.assertEqual(check_native_request_off(self.db, self.docs[5], self._payload())["level"], "yellow")

        result = create_native_request_off(self.db, self.docs[5], self._payload())
        self.assertTrue(result["ok"])
        self.assertEqual(result["level"], "red")
        self.assertTrue(result["warnings"][0].startswith("Sent with a red alert"))
        self.assertEqual(self.db.query(DayOff).count(), before + 1)
        alert = self.db.query(AdminNotification).one()
        self.assertEqual((alert.kind, alert.title), ("time_off_red", "Red alert: time off"))
        self.assertIn("CJ (approved)", alert.body)

    @patch("app.native_request_off_service.send_time_off_request_copy", return_value=False)
    @patch("app.native_request_off_service.send_native_push_to_surgeon")
    def test_yellow_doctor_request_is_approved_on_the_spot(self, push, email):
        self._off(self.docs[0])
        with patch("app.admin_dayoff_service.send_push_to_surgeon"), \
             patch("app.admin_dayoff_service.send_time_off_decision_email", create=True):
            result = create_native_request_off(self.db, self.docs[5], self._payload())
        self.assertTrue(result["ok"])
        self.assertEqual(result["status"], "approved")
        self.assertEqual(result["warnings"][0], "Approved: within the time-off rules.")
        self.assertTrue(any("Heads up" in w for w in result["warnings"]))
        # Inside the rules: nothing for Shannon to approve.
        self.assertEqual(self.db.query(AdminNotification).filter_by(kind="day_off_request").count(), 0)

    def _book(self, doc, kind="surgical", n=1):
        from app.models import ScheduleCardActivity
        card = self.db.query(ScheduleCard).filter_by(surgeon_id=doc.id, date=DAY, session="am").one()
        for i in range(n):
            self.db.add(ScheduleCardActivity(
                schedule_card_id=card.id, surgeon_id=doc.id, activity_date=DAY, session="am",
                activity_type=kind, patient_name=f"Patient {i}", procedure="", source_system="fax",
                source_record_key=f"t|{doc.id}|{kind}|{i}", identity_key=f"t{doc.id}{kind}{i}", is_active=True,
            ))
        self.db.commit()

    def test_booked_case_or_clinic_makes_request_red(self):
        self._book(self.docs[5], "surgical", 2)
        self._book(self.docs[5], "clinic", 3)
        result = self._check(self.docs[5])
        self.assertEqual(result.level, "red")
        self.assertIn("2 cases and 3 visits booked", result.surgeon_message())
        self.assertEqual(result.day_lines()[0]["booked"], "2 cases and 3 visits booked")
        # Exempt doctors still get the booked-work red (only the off count is skipped).
        self.docs[5].time_off_exempt = True
        self.db.commit()
        self.assertEqual(self._check(self.docs[5]).level, "red")

    def test_shannon_red_day_cards_start_tomorrow_and_clear(self):
        from app.time_off_capacity import sync_red_day_alerts
        admin = self.db.query(AdminUser).one()
        for doc in self.docs[:3]:
            self._off(doc)
        self._book(self.docs[4], "clinic", 1)
        self._off(self.docs[4])
        sync_red_day_alerts(self.db, admin.id)
        cards = self.db.query(AdminNotification).filter_by(kind="time_off_red_day").all()
        titles = sorted(c.title for c in cards)
        self.assertEqual(titles, ["Red day: Winter Garden", "Red: MS has work booked during time off"])
        self.assertTrue(any("1 visit booked while off" in c.body for c in cards))
        sync_red_day_alerts(self.db, admin.id)  # no duplicates
        self.assertEqual(self.db.query(AdminNotification).filter_by(kind="time_off_red_day").count(), 2)
        # Fixed: one doctor's time off is denied and the clinic visit cancelled -> cards go away.
        for doc in self.docs[:2]:
            self.db.query(DayOff).filter_by(surgeon_id=doc.id).one().status = "denied"
        from app.models import ScheduleCardActivity
        self.db.query(ScheduleCardActivity).update({"is_active": False})
        self.db.commit()
        sync_red_day_alerts(self.db, admin.id)
        self.assertEqual(self.db.query(AdminNotification).filter_by(kind="time_off_red_day").count(), 0)

    @patch("app.native_request_off_service.send_time_off_request_copy", return_value=False)
    @patch("app.native_request_off_service.send_native_push_to_surgeon")
    @patch("app.push.send_sms")
    def test_red_edit_is_saved_and_alerts(self, sms, push, email):
        for doc in self.docs[:2]:
            self._off(doc)
        other_day = _next_weekday(40)
        mine = DayOff(surgeon_id=self.docs[5].id, start_date=other_day, end_date=other_day,
                      status="pending", reason="Vacation")
        self.db.add(mine)
        self.db.commit()
        result = update_native_request_off(self.db, self.docs[5], mine.id, self._payload())
        self.assertTrue(result["ok"])
        self.db.refresh(mine)
        self.assertEqual(mine.start_date, DAY)
        self.assertEqual(self.db.query(AdminNotification).filter_by(kind="time_off_red").count(), 1)


    @patch("app.native_request_off_service.send_time_off_request_copy", return_value=False)
    @patch("app.native_request_off_service.send_native_push_to_surgeon")
    @patch("app.push.send_sms")
    def test_red_alert_links_to_request_stays_then_clears(self, sms, push, email):
        from app.admin_notification_ack import notification_is_informational
        from app.admin_notification_href import admin_notification_href
        from app.admin_settings_page_service import recent_admin_notifications
        import json as _json

        for doc in self.docs[:2]:
            self._off(doc)
        result = create_native_request_off(self.db, self.docs[5], self._payload())
        alert = self.db.query(AdminNotification).filter_by(kind="time_off_red").one()
        admin_id = alert.admin_user_id
        self.assertFalse(notification_is_informational(alert))
        self.assertIn(f"focus={result['request']['id']}", admin_notification_href(alert.kind, _json.loads(alert.payload)))
        self.assertIn(alert.id, [row.id for row in recent_admin_notifications(self.db, admin_id)])
        # Shannon handles it: the red card goes away.
        mine = self.db.get(DayOff, result["request"]["id"])
        mine.status = "approved"
        self.db.commit()
        recent_admin_notifications(self.db, admin_id)
        self.assertEqual(self.db.query(AdminNotification).filter_by(kind="time_off_red").count(), 0)


    def test_approval_is_stamped_and_shown_in_eastern(self):
        from datetime import datetime as _dt
        from app.admin_dayoff_service import approve_dayoff, dayoff_stamps

        row = self._off(self.docs[0], status="pending")
        row.created_at = _dt(2026, 11, 20, 15, 5)  # 10:05 AM Eastern
        self.db.commit()
        self.assertEqual(dayoff_stamps(row), "Requested Nov 20 10:05 AM")
        with patch("app.admin_dayoff_service.send_push_to_surgeon"), \
             patch("app.admin_dayoff_service.send_time_off_decision_email", create=True):
            approve_dayoff(self.db, row.id, approved_by=None)
        self.db.refresh(row)
        self.assertIsNotNone(row.approved_at)
        self.assertIn("· Approved ", dayoff_stamps(row))


    def test_any_admin_gets_red_day_cards_even_with_notices_off(self):
        from app.time_off_capacity import sync_red_day_alerts
        quiet = AdminUser(username="don", email="d@example.com", password_hash="x",
                          is_active=True, notify_day_off_requests=False)
        self.db.add(quiet)
        self.db.commit()
        for doc in self.docs[:3]:
            self._off(doc)
        sync_red_day_alerts(self.db, quiet.id)
        self.assertEqual(
            self.db.query(AdminNotification).filter_by(admin_user_id=quiet.id, kind="time_off_red_day").count(), 1)


    def test_clinic_or_grid_shows_lines_on_off_na_card_and_flags_red(self):
        from app.schedule_card_projection_service import card_grid_page_data
        doc = self.docs[0]
        self._off(doc)
        self._book(doc, "clinic", 13)
        self._book(doc, "surgical", 1)
        cell = card_grid_page_data(self.db, DAY, DAY)["grid"][doc.id][DAY]["am"]
        self.assertEqual(cell["label"], "NA")
        self.assertEqual(cell["count"], 14)
        self.assertEqual(cell["count_label"], "1 case · 13 visits")
        self.assertTrue(cell["booked_while_off"])
        # The next schedule takes them off: zero, and the flag clears.
        from app.models import ScheduleCardActivity
        self.db.query(ScheduleCardActivity).update({"is_active": False})
        self.db.commit()
        cell = card_grid_page_data(self.db, DAY, DAY)["grid"][doc.id][DAY]["am"]
        self.assertEqual(cell["count"], 0)
        self.assertFalse(cell["booked_while_off"])


if __name__ == "__main__":
    unittest.main()
