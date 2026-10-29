"""One test (or more) per rule in Don's 12 fax-ingest rules (Oct 29, 2026)."""

import json
import os

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
import unittest
from datetime import date, time, timedelta
from unittest.mock import Mock, patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.fax_card_fill import _STATEMENTS as FILL_STATEMENTS
from app.fax_ingest_engine import ReviewedFaxRow, split_future_rows, stage_reviewed_rows
from app.fax_snapshot_service import apply_staged_snapshot
from app.migrate_fax_ingest import create_applicable_view
from app.models import (
    AdminNotification,
    AdminUser,
    Base,
    DayOff,
    FaxDocument,
    FaxRowDecision,
    FaxRoomCode,
    Location,
    ORBlockAssignment,
    ORBlockInstance,
    ScheduleCard,
    ScheduleCardActivity,
    ScheduleCardWeek,
    ScheduleWarning,
    Surgeon,
)
from app.routers.api_ingest import VisualFaxRowIn, VisualScheduleBatch, ingest_visual_schedule_route

DAY = date(2026, 9, 22)  # Tuesday


class DonRulesTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.db = sessionmaker(bind=self.engine)()
        self.surgeon = Surgeon(first_name="Jorge", last_name="Florin", email="jf@example.com", is_active=True)
        self.ap_ov = Location(name="Apopka Clinic", abbreviation="AP-OV", location_type="clinic", is_active=True)
        self.wg_or = Location(name="Winter Garden OR", abbreviation="WG-OR", location_type="hospital", is_active=True)
        self.al_or = Location(name="Altamonte OR", abbreviation="AL-OR", location_type="hospital", is_active=True)
        self.db.add_all([self.surgeon, self.ap_ov, self.wg_or, self.al_or])
        self.db.add_all([
            AdminUser(username="szeh", email="s@example.com", password_hash="x", role="superadmin", is_active=True),
            AdminUser(username="dnaile", email="d@example.com", password_hash="x", role="superadmin", is_active=True),
            AdminUser(username="angel", email="a@example.com", password_hash="x", role="scheduler", is_active=True),
        ])
        self.db.flush()
        self.week = ScheduleCardWeek(surgeon_id=self.surgeon.id, week_start=date(2026, 9, 21), master_revision="t")
        self.db.add(self.week)
        self.db.flush()
        self.am = self._card(DAY, "am", "assigned", self.wg_or.id)
        self.pm = self._card(DAY, "pm", "na", None)
        self.db.add(FaxDocument(external_fax_id=191, source_label="t", status="rendered"))
        self.db.add(FaxDocument(external_fax_id=192, source_label="t", status="rendered"))
        self.db.commit()
        with self.engine.begin() as conn:
            create_applicable_view(conn)  # seeds fax_room_codes now that locations exist

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def _card(self, day, session, state, location_id):
        card = ScheduleCard(
            week_id=self.week.id, surgeon_id=self.surgeon.id, date=day, session=session,
            baseline_state=state, effective_state=state,
            baseline_location_id=location_id, effective_location_id=location_id, source="master",
        )
        self.db.add(card)
        self.db.flush()
        return card

    def _block(self, location, start, end, day=DAY):
        block = ORBlockInstance(location_id=location.id, date=day, session="am" if start < time(12) else "pm",
                                start_time=start, end_time=end, status="assigned",
                                assigned_surgeon_id=self.surgeon.id)
        self.db.add(block)
        self.db.flush()
        self.db.add(ORBlockAssignment(block_instance_id=block.id, surgeon_id=self.surgeon.id, start_time=start))
        self.db.commit()

    def _row(self, patient, *, day=DAY, at=time(8, 0), room="WGD S07", surgeon="Jorge Florin",
             initials="JF", flags=None, row_type="surgical", page=2):
        return ReviewedFaxRow(page=page, surgeon_initials=initials, surgeon_name=surgeon, case_date=day,
                              start_time=at, row_type=row_type, room=room, patient_name=patient,
                              procedure="p", extraction_flags=flags)

    def _stage(self, rows, fax=191):
        staged = stage_reviewed_rows(self.db, external_fax_id=fax, source_label="t", rows=rows)
        self.db.commit()
        return staged

    def _reasons(self, run_id):
        return [d.reason_code for d in self.db.query(FaxRowDecision).order_by(FaxRowDecision.id)
                if d.fax_row.run_id == run_id] if hasattr(FaxRowDecision, "fax_row") else \
            [r for (r,) in self.db.execute(__import__("sqlalchemy").text(
                "SELECT d.reason_code FROM fax_row_decisions d JOIN fax_ingest_rows r ON r.id = d.fax_row_id "
                "WHERE r.run_id = :run ORDER BY r.id"), {"run": run_id})]

    # Rule 1: ingest never creates, deletes or edits cards; it only adds lines.
    def test_rule1_cards_are_untouched_and_missing_card_is_held(self):
        before = [(c.id, c.baseline_state, c.effective_state, c.effective_location_id)
                  for c in self.db.query(ScheduleCard).order_by(ScheduleCard.id)]
        staged = self._stage([self._row("Has, Card"), self._row("No, Card", day=DAY + timedelta(days=1))])
        result = apply_staged_snapshot(self.db, source_fax_id=191, run_id=staged["runId"])
        after = [(c.id, c.baseline_state, c.effective_state, c.effective_location_id)
                 for c in self.db.query(ScheduleCard).order_by(ScheduleCard.id)]
        self.assertEqual(before, after)
        self.assertEqual(result["cardsCreated"], 0)
        self.assertEqual(staged["report"]["heldByReason"], {"missing_scaffold": 1})
        self.assertEqual([a.patient_name for a in self.db.query(ScheduleCardActivity)], ["Has, Card"])

    # Rule 2: never deactivate existing lines; the retire SQL is gone.
    def test_rule2_no_deactivation_statement_and_lines_stay_active(self):
        self.assertFalse(any("is_active = FALSE" in s for s in FILL_STATEMENTS))
        self.assertFalse(any("fax_line_absences" in s for s in FILL_STATEMENTS))
        first = self._stage([self._row("A, Patient"), self._row("B, Patient", at=time(9))])
        apply_staged_snapshot(self.db, source_fax_id=191, run_id=first["runId"])
        second = self._stage([self._row("A, Patient")], fax=192)
        result = apply_staged_snapshot(self.db, source_fax_id=192, run_id=second["runId"])
        self.assertEqual(result["linesDeactivated"], 0)
        self.assertEqual(result["report"]["linesDeactivated"], 0)
        self.assertTrue(all(a.is_active for a in self.db.query(ScheduleCardActivity)))

    # Rule 3: today-or-earlier rows are skipped entirely (not staged, not counted).
    def test_rule3_today_and_past_rows_are_skipped(self):
        today = date(2026, 10, 29)
        rows = [self._row("Past", day=today - timedelta(days=1)), self._row("Today", day=today),
                self._row("Tomorrow", day=today + timedelta(days=1)), self._row("Bad", day="not-a-date")]
        kept, skipped = split_future_rows(rows, today=today)
        self.assertEqual([r.patient_name for r in kept], ["Tomorrow", "Bad"])
        self.assertEqual(skipped, 2)

    def test_rule3_api_route_never_stages_past_rows(self):
        body = VisualScheduleBatch(source_fax_id=7, rows=[
            VisualFaxRowIn(surgeon_initials="JF", case_date="2020-01-02", start_time="0715",
                           row_type="surgical", room="MIN S05", patient_name="Old, Row")])
        with patch("app.routers.api_ingest.stage_reviewed_rows") as stage:
            result = ingest_visual_schedule_route(body, db=Mock())
        stage.assert_not_called()
        self.assertEqual(result["result"]["skippedPast"], 1)

    # Rule 4: no day-span limit (Epic runs a month+ out, into Feb 2027).
    def test_rule4_long_span_fax_applies(self):
        far = date(2027, 2, 9)
        self._card(far, "am", "assigned", self.wg_or.id)
        self.db.commit()
        staged = self._stage([self._row("Near, Patient"), self._row("Far, Patient", day=far)])
        result = apply_staged_snapshot(self.db, source_fax_id=191, run_id=staged["runId"])
        self.assertEqual(result["range"], {"start": DAY.isoformat(), "end": far.isoformat()})
        self.assertEqual(self.db.query(ScheduleCardActivity).count(), 2)

    # Rule 5: the newer fax wins for a day (same patient/time is updated, not duplicated).
    def test_rule5_newer_fax_updates_the_same_line(self):
        first = self._stage([self._row("Same, Patient")])
        apply_staged_snapshot(self.db, source_fax_id=191, run_id=first["runId"])
        newer = ReviewedFaxRow(page=1, surgeon_initials="JF", surgeon_name="Jorge Florin", case_date=DAY,
                               start_time=time(8, 0), row_type="surgical", room="WGD S07",
                               patient_name="Same, Patient", procedure="newer procedure")
        second = self._stage([newer], fax=192)
        apply_staged_snapshot(self.db, source_fax_id=192, run_id=second["runId"])
        lines = self.db.query(ScheduleCardActivity).all()
        self.assertEqual(len(lines), 1)
        self.assertEqual((lines[0].source_fax_id, lines[0].procedure), (192, "newer procedure"))
        older_again = self._stage([self._row("Same, Patient")], fax=191)
        with self.assertRaisesRegex(ValueError, "newer fax was already applied"):
            apply_staged_snapshot(self.db, source_fax_id=191, run_id=older_again["runId"])

    # Rule 6: a patient name is never a surgeon; unknown surgeons are held.
    def test_rule6_patient_name_as_surgeon_is_held(self):
        staged = self._stage([
            self._row("Florin, Jorge [123]", surgeon="Jorge Florin"),
            self._row("Real, Patient", surgeon="Zed Nobody", initials="ZN"),
        ])
        self.assertEqual(self._reasons(staged["runId"]), ["unknown_surgeon", "unknown_surgeon"])

    # Rule 7: real room -> its location; placeholder -> card; disagreement -> hold.
    def test_rule7_room_codes(self):
        codes = {c.code: c for c in self.db.query(FaxRoomCode)}
        self.assertEqual(codes["AHMGGENSRG"].kind, "placeholder")
        self.assertEqual(codes["ALT S01"].location_id, self.al_or.id)
        staged = self._stage([
            self._row("Placeholder, Room", room="AHMGGENSRG"),          # card WG-OR
            self._row("Real, Room", room="ALT S01", at=time(9)),        # AL-OR vs WG-OR card? both OR
        ])
        rows = {r.patient_name: r.source_location_id for r in
                self.db.execute(__import__("sqlalchemy").text(
                    "SELECT patient_name, source_location_id FROM fax_ingest_rows WHERE run_id=:r"),
                    {"r": staged["runId"]})}
        self.assertEqual(rows["Placeholder, Room"], self.wg_or.id)
        self.assertEqual(rows["Real, Room"], self.al_or.id)

    def test_rule7_room_disagreeing_with_block_is_held(self):
        self._block(self.wg_or, time(7), time(12))
        staged = self._stage([self._row("Disagree, Room", room="ALT S01")])
        self.assertEqual(self._reasons(staged["runId"]), ["location_conflict"])

    # Rule 8: the card type decides clinic vs OR.
    def test_rule8_card_type_decides_row_type(self):
        clinic_day = DAY + timedelta(days=1)
        self._card(clinic_day, "am", "assigned", self.ap_ov.id)
        self.db.commit()
        staged = self._stage([
            self._row("OR, Card", row_type="clinic"),
            self._row("Clinic, Card", day=clinic_day, room="AHMGGENSRG", row_type="surgical"),
        ])
        types = dict(self.db.execute(__import__("sqlalchemy").text(
            "SELECT patient_name, row_type FROM fax_ingest_rows WHERE run_id=:r"), {"r": staged["runId"]}).all())
        self.assertEqual(types, {"OR, Card": "surgical", "Clinic, Card": "clinic"})

    # Rule 9: NA means open; adding lines to an NA card is not a conflict.
    def test_rule9_na_card_accepts_lines_without_conflict(self):
        self._block(self.wg_or, time(12), time(17))
        staged = self._stage([self._row("Afternoon, Patient", at=time(13))])
        result = apply_staged_snapshot(self.db, source_fax_id=191, run_id=staged["runId"])
        line = self.db.query(ScheduleCardActivity).one()
        self.assertEqual(line.schedule_card_id, self.pm.id)
        self.assertEqual(result["report"]["conflictsFlagged"], 0)
        self.assertEqual(self.db.query(AdminNotification).count(), 0)

    # Rule 10: OFF / approved OFF is a conflict: line entered, Shannon + Don notified.
    def _warning_codes(self):
        return sorted(w.warning_code for w in self.db.query(ScheduleWarning).all())

    # Rule 10 (amended): OFF day -> line entered + in-CAL card flag, no notification.
    def test_rule10_off_card_enters_line_and_flags_card_in_cal(self):
        off_day = DAY + timedelta(days=1)
        self._card(off_day, "am", "off", self.wg_or.id)
        self.db.commit()
        staged = self._stage([self._row("Off, Day", day=off_day)])
        result = apply_staged_snapshot(self.db, source_fax_id=191, run_id=staged["runId"])
        self.assertEqual(self.db.query(ScheduleCardActivity).count(), 1)
        self.assertEqual(self.db.query(AdminNotification).count(), 0)
        self.assertEqual(self._warning_codes(), ["off_collision"])
        self.assertEqual(result["report"]["conflictsFlagged"], 1)
        self.assertNotIn("adminConflictNotices", result)

    def test_rule10_approved_day_off_on_assigned_card_flags_card_in_cal(self):
        self.db.add(DayOff(surgeon_id=self.surgeon.id, start_date=DAY, end_date=DAY, status="approved",
                           is_full_day=True))
        self.db.commit()
        staged = self._stage([self._row("Approved, Off")])
        result = apply_staged_snapshot(self.db, source_fax_id=191, run_id=staged["runId"])
        self.assertEqual(self.db.query(ScheduleCardActivity).count(), 1)
        self.assertEqual(self.db.query(AdminNotification).count(), 0)
        self.assertEqual(self._warning_codes(), ["approved_day_off"])
        self.assertNotIn("Approved, Off", self.db.query(ScheduleWarning).one().detail or "")
        self.assertEqual(result["report"]["conflictsFlagged"], 1)

    # Don's BIG RULE: no notification of any kind goes out during fax ingest.
    def test_big_rule_ingest_sends_zero_notifications(self):
        off_day = DAY + timedelta(days=1)
        self._card(off_day, "am", "off", self.wg_or.id)
        self.db.add(DayOff(surgeon_id=self.surgeon.id, start_date=DAY, end_date=DAY, status="approved",
                           is_full_day=True))
        self.db.commit()
        with patch("app.push.create_admin_notification") as admin_note, \
             patch("app.push.send_push_to_surgeon") as push, \
             patch("app.push.send_push_to_all") as push_all, \
             patch("app.sms_service.send_sms") as sms, \
             patch("app.email_service.send_email") as email:
            staged = self._stage([self._row("Off, Day", day=off_day), self._row("Approved, Off"),
                                  self._row("Who", surgeon="Zed Nobody", initials="ZN"),
                                  self._row("Smudged", at=time(9), flags="ocr_uncertain")])
            result = apply_staged_snapshot(self.db, source_fax_id=191, run_id=staged["runId"])
        for sender in (admin_note, push, push_all, sms, email):
            sender.assert_not_called()
        self.assertEqual(self.db.query(AdminNotification).count(), 0)
        self.assertEqual(result["notificationsSent"], 0)
        self.assertEqual(result["report"]["conflictsFlagged"], 2)

    def test_big_rule_ingest_modules_import_no_senders(self):
        import pathlib
        app_dir = pathlib.Path(__file__).resolve().parents[1] / "app"
        banned = ("send_email", "send_sms", "send_push", "create_admin_notification",
                  "AdminNotification(", "send_notification_email")
        for name in ("fax_ingest_engine.py", "fax_snapshot_service.py", "fax_card_fill.py",
                     "fax_off_day_conflicts.py", "fax_ingest_guardrails.py", "fax_room_codes.py",
                     "routers/api_ingest.py"):
            source = (app_dir / name).read_text()
            for word in banned:
                self.assertNotIn(word, source, f"{name} must not send notifications ({word})")

    # Rule 11: flags are per row; one flagged row never holds the page.
    def test_rule11_flags_are_per_row(self):
        staged = self._stage([self._row("Clean, One"), self._row("Smudged", at=time(9), flags="ocr_uncertain"),
                              self._row("Clean, Two", at=time(10))])
        self.assertEqual(self._reasons(staged["runId"]), ["existing_card", "extraction_flagged", "existing_card"])
        result = apply_staged_snapshot(self.db, source_fax_id=191, run_id=staged["runId"])
        self.assertEqual(result["rows"], 2)

    # Rule 12: each run reports added / held by reason / conflicts / deactivated=0.
    def test_rule12_run_report(self):
        staged = self._stage([self._row("Ok"), self._row("Who", surgeon="Zed Nobody", initials="ZN")])
        self.assertEqual(staged["report"], {"linesAdded": 1, "linesHeld": 1,
                                            "heldByReason": {"unknown_surgeon": 1},
                                            "conflictsFlagged": 0, "linesDeactivated": 0})
        result = apply_staged_snapshot(self.db, source_fax_id=191, run_id=staged["runId"])
        self.assertEqual(result["report"]["linesAdded"], 1)
        self.assertEqual(result["report"]["linesDeactivated"], 0)


if __name__ == "__main__":
    unittest.main()
