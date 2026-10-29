import json
import os
import unittest
from datetime import date, datetime, time
from unittest.mock import patch

from sqlalchemy.exc import IntegrityError

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("SECRET_KEY", "test-secret")

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.fax_ingest_engine import ReviewedFaxRow, stage_reviewed_rows
from app.fax_restore_service import restore_fax_snapshot
from app.fax_snapshot_service import apply_staged_snapshot
from app.native_home_items import empty_days
from app.native_schedule_feed import append_native_schedule
from app.schedule_build_backup_service import revert_schedule_build_backup
from app.migrate_fax_ingest import create_applicable_view
from app.models import (
    FaxRowDecision,
    Base,
    CoSurgeonPair,
    FaxDocument,
    FaxIngestRow,
    FaxIngestRun,
    FaxRestoreLine,
    FaxRestoreSet,
    Location,
    ORBlockAssignment,
    ORBlockInstance,
    ScheduleBuildBackup,
    ScheduleCard,
    ScheduleCardActivity,
    ScheduleCardWeek,
    ScheduleWarning,
    Surgeon,
)


class FaxSnapshotServiceTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        with self.engine.begin() as conn:
            create_applicable_view(conn)
        self.Session = sessionmaker(bind=self.engine)
        self.db = self.Session()
        self.surgeon = Surgeon(
            first_name="Jorge",
            last_name="Florin",
            email="jf@example.com",
            is_active=True,
        )
        self.ap_ov = Location(
            name="Apopka Clinic",
            abbreviation="AP-OV",
            location_type="clinic",
            is_active=True,
        )
        self.wg_or = Location(
            name="Winter Garden OR",
            abbreviation="WG-OR",
            location_type="hospital",
            is_active=True,
        )
        self.alt_or = Location(
            name="Altamonte OR",
            abbreviation="AL-OR",
            location_type="hospital",
            is_active=True,
        )
        self.db.add_all([self.surgeon, self.ap_ov, self.wg_or, self.alt_or])
        self.db.flush()
        week = ScheduleCardWeek(
            surgeon_id=self.surgeon.id,
            week_start=date(2026, 9, 21),
            master_revision="test",
        )
        self.db.add(week)
        self.db.flush()
        self.db.add_all([
            ScheduleCard(
                week_id=week.id,
                surgeon_id=self.surgeon.id,
                date=date(2026, 9, 22),
                session="am",
                baseline_state="assigned",
                effective_state="assigned",
                baseline_location_id=self.ap_ov.id,
                effective_location_id=self.ap_ov.id,
                source="master",
            ),
            ScheduleCard(
                week_id=week.id,
                surgeon_id=self.surgeon.id,
                date=date(2026, 9, 22),
                session="pm",
                baseline_state="na",
                effective_state="na",
                source="master",
            ),
        ])
        self.db.add(FaxDocument(external_fax_id=191, source_label="test", status="rendered"))
        self.db.commit()

    def _assign_block(self, location, start, end, day=date(2026, 9, 22)):
        block = ORBlockInstance(
            location_id=location.id,
            date=day,
            session="am" if start < time(12, 0) else "pm",
            start_time=start,
            end_time=end,
            status="assigned",
            assigned_surgeon_id=self.surgeon.id,
        )
        self.db.add(block)
        self.db.flush()
        self.db.add(ORBlockAssignment(
            block_instance_id=block.id,
            surgeon_id=self.surgeon.id,
            start_time=start,
        ))
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def test_daily_snapshot_fills_existing_cards_and_never_creates_cards(self):
        self._assign_block(self.wg_or, time(11, 30), time(17, 0))
        staged = stage_reviewed_rows(
            self.db,
            external_fax_id=191,
            source_label="test",
            surgeon_scope=["JF"],
            rows=[
                ReviewedFaxRow(
                    page=2,
                    surgeon_initials="JF",
                    surgeon_name="Jorge Florin",
                    case_date=date(2026, 9, 22),
                    start_time=time(11, 0),
                    row_type="clinic",
                    room="AHMGGENSRG",
                    patient_name="Clinic, Patient",
                ),
                ReviewedFaxRow(
                    page=2,
                    surgeon_initials="JF",
                    surgeon_name="Jorge Florin",
                    case_date=date(2026, 9, 22),
                    start_time=time(11, 45),
                    row_type="surgical",
                    room="WGD S07",
                    patient_name="Case, Patient",
                    procedure="Robotic case",
                ),
            ],
        )
        self.db.commit()
        staged_rows = self.db.query(FaxIngestRow).filter_by(run_id=staged["runId"]).all()
        sessions = {(row.patient_name, row.session) for row in staged_rows}
        self.assertIn(("Clinic, Patient", "am"), sessions)
        self.assertIn(("Case, Patient", "pm"), sessions)

        result = apply_staged_snapshot(
            self.db,
            source_fax_id=191,
            run_id=staged["runId"],
        )

        self.assertEqual(result["cardsCreated"], 0)
        self.assertEqual(result["cardsChanged"], 0)
        self.assertEqual(self.db.query(ScheduleCard).count(), 2)
        pm = self.db.query(ScheduleCard).filter_by(session="pm").one()
        self.assertEqual(pm.baseline_state, "na")
        self.assertEqual(pm.effective_state, "na")
        self.assertIsNone(pm.effective_location_id)
        self.assertEqual(pm.source, "master")
        self.assertEqual(pm.version, 1)
        am = self.db.query(ScheduleCard).filter_by(session="am").one()
        activities = {
            row.activity_type: row
            for row in self.db.query(ScheduleCardActivity).filter_by(is_active=True)
        }
        self.assertEqual(activities["clinic"].schedule_card_id, am.id)
        self.assertEqual(activities["clinic"].patient_name, "Clinic, Patient")
        self.assertEqual(activities["surgical"].schedule_card_id, pm.id)
        self.assertEqual(activities["surgical"].patient_name, "Case, Patient")
        self.assertEqual(activities["surgical"].source_fax_id, 191)
        self.assertEqual(activities["clinic"].source_fax_id, 191)
        self.assertTrue(activities["surgical"].source_record_key.startswith("191|"))
        self.assertEqual(self.db.query(FaxIngestRow).filter_by(run_id=staged["runId"]).count(), 0)
        backup = self.db.query(ScheduleBuildBackup).one()
        payload = json.loads(backup.payload_json)
        self.assertEqual(payload["kind"], "fax_snapshot")
        self.assertEqual(len(payload["schedule_cards"]), 2)
        self.assertEqual(result["notificationsSent"], 0)

        reverted = revert_schedule_build_backup(
            self.db,
            backup_id=backup.id,
            admin_id=None,
        )
        self.assertTrue(reverted["ok"])
        restored_pm = self.db.query(ScheduleCard).filter_by(session="pm").one()
        self.assertEqual(restored_pm.effective_state, "na")

    def test_daily_snapshot_updates_expanded_patient_name_without_duplicate(self):
        staged = stage_reviewed_rows(
            self.db,
            external_fax_id=191,
            source_label="test",
            surgeon_scope=["JF"],
            rows=[
                ReviewedFaxRow(
                    page=2,
                    surgeon_initials="JF",
                    surgeon_name="Jorge Florin",
                    case_date=date(2026, 9, 22),
                    start_time=time(9, 0),
                    row_type="surgical",
                    room="WGD S07",
                    patient_name="Williams, Robert Alexander",
                    procedure="Current procedure",
                ),
            ],
        )
        self.db.commit()

        result = apply_staged_snapshot(
            self.db,
            source_fax_id=191,
            run_id=staged["runId"],
        )

        # Rule 8: the AM card is a clinic (AP-OV), so the card type makes this a clinic line.
        self.assertEqual(result["report"]["linesAdded"], 1)
        self.assertEqual(result["surgicalCancelled"], 0)
        am = self.db.query(ScheduleCard).filter_by(session="am").one()
        line = self.db.query(ScheduleCardActivity).filter_by(is_active=True).one()
        self.assertEqual(line.schedule_card_id, am.id)
        self.assertEqual(line.patient_name, "Williams, Robert Alexander")
        self.assertEqual(line.procedure, "Current procedure")
        self.assertEqual(self.db.query(ScheduleCardActivity).count(), 1)

    def test_daily_snapshot_keeps_mixed_facilities_on_one_session_card(self):
        self._assign_block(self.wg_or, time(12, 0), time(13, 30))
        self._assign_block(self.alt_or, time(13, 30), time(17, 0))
        staged = stage_reviewed_rows(
            self.db,
            external_fax_id=191,
            source_label="test",
            surgeon_scope=["JF"],
            rows=[
                ReviewedFaxRow(
                    page=2,
                    surgeon_initials="JF",
                    surgeon_name="Jorge Florin",
                    case_date=date(2026, 9, 22),
                    start_time=time(12, 30),
                    row_type="surgical",
                    room="WGD S07",
                    patient_name="First, Patient",
                    procedure="First case",
                ),
                ReviewedFaxRow(
                    page=2,
                    surgeon_initials="JF",
                    surgeon_name="Jorge Florin",
                    case_date=date(2026, 9, 22),
                    start_time=time(13, 45),
                    row_type="surgical",
                    room="ALT S07",
                    patient_name="Second, Patient",
                    procedure="Second case",
                ),
            ],
        )
        self.db.commit()

        result = apply_staged_snapshot(self.db, source_fax_id=191, run_id=staged["runId"])

        lines = self.db.query(ScheduleCardActivity).order_by(ScheduleCardActivity.start_time).all()
        pm = self.db.query(ScheduleCard).filter_by(session="pm").one()
        self.assertEqual(self.db.query(ScheduleCard).count(), 2)
        self.assertEqual([line.schedule_card_id for line in lines], [pm.id, pm.id])
        self.assertEqual([line.location_id for line in lines], [self.wg_or.id, self.alt_or.id])
        self.assertTrue(any(item["code"] == "mixed_facilities_in_session" for item in result["baselineConflicts"]))
        warning = self.db.query(ScheduleWarning).one()
        self.assertEqual(warning.warning_code, "mixed_facilities_in_session")
        self.assertEqual(warning.schedule_card_id, pm.id)
        self.assertEqual(warning.source_fax_id, 191)
        self.assertNotIn("Patient", warning.detail or "")

    def test_validated_session_wins_when_case_location_matches_other_card(self):
        pm_card = self.db.query(ScheduleCard).filter_by(session="pm").one()
        wg_or_id = self.wg_or.id
        pm_card.baseline_location_id = wg_or_id
        pm_card.effective_location_id = wg_or_id
        pm_card.baseline_state = "assigned"
        pm_card.effective_state = "assigned"
        self.db.commit()
        self._assign_block(self.alt_or, time(7, 0), time(9, 0))
        self._assign_block(self.wg_or, time(9, 0), time(12, 0))
        staged = stage_reviewed_rows(
            self.db,
            external_fax_id=191,
            source_label="test",
            surgeon_scope=["JF"],
            rows=[
                ReviewedFaxRow(
                    page=2,
                    surgeon_initials="JF",
                    surgeon_name="Jorge Florin",
                    case_date=date(2026, 9, 22),
                    start_time=time(7, 30),
                    row_type="surgical",
                    room="ALT S01",
                    patient_name="First, Patient",
                    procedure="First case",
                ),
                ReviewedFaxRow(
                    page=2,
                    surgeon_initials="JF",
                    surgeon_name="Jorge Florin",
                    case_date=date(2026, 9, 22),
                    start_time=time(9, 15),
                    row_type="surgical",
                    room="WGD S03",
                    patient_name="Second, Patient",
                    procedure="Second case",
                ),
            ],
        )
        self.db.commit()

        # Don: real rooms (ALT S01, WGD S03) set the location themselves -> rows go on the cards.
        reasons = [d.reason_code for d in self.db.query(FaxRowDecision).order_by(FaxRowDecision.id)]
        self.assertEqual(reasons, ["existing_card", "existing_card"])
        apply_staged_snapshot(self.db, source_fax_id=191, run_id=staged["runId"])

    def test_post_commit_cleanup_failure_does_not_report_apply_failure(self):
        staged = stage_reviewed_rows(
            self.db,
            external_fax_id=191,
            source_label="test",
            surgeon_scope=["JF"],
            rows=[
                ReviewedFaxRow(
                    page=2,
                    surgeon_initials="JF",
                    surgeon_name="Jorge Florin",
                    case_date=date(2026, 9, 22),
                    start_time=time(9, 0),
                    row_type="surgical",
                    room="WGD S07",
                    patient_name="Cleanup, Patient",
                    procedure="Test procedure",
                ),
            ],
        )
        self.db.commit()

        with patch(
            "app.fax_snapshot_service.prune_immutable_fax_sources",
            side_effect=PermissionError("read-only source"),
        ):
            result = apply_staged_snapshot(self.db, source_fax_id=191, run_id=staged["runId"])

        self.assertTrue(result["ok"])
        self.assertEqual(result["cardsCreated"], 0)
        self.assertEqual(len(result["cleanupErrors"]), 1)
        self.assertIn("read-only source", result["cleanupErrors"][0])
        self.assertEqual(self.db.query(ScheduleCardActivity).filter_by(is_active=True).count(), 1)

    def _row(self, patient, day=date(2026, 9, 22), flags=None):
        return ReviewedFaxRow(
            page=2,
            surgeon_initials="JF",
            surgeon_name="Jorge Florin",
            case_date=day,
            start_time=time(13, 0),
            row_type="surgical",
            room="WGD S07",
            patient_name=patient,
            procedure="Test procedure",
            extraction_flags=flags,
        )

    def test_flagged_row_is_skipped_and_the_rest_applies(self):
        self._assign_block(self.wg_or, time(12, 0), time(17, 0))
        staged = stage_reviewed_rows(
            self.db,
            external_fax_id=191,
            source_label="test",
            surgeon_scope=["JF"],
            rows=[self._row("Clean, Patient"), self._row("Smudged, Patient", flags="missing_room")],
        )
        self.db.commit()

        result = apply_staged_snapshot(self.db, source_fax_id=191, run_id=staged["runId"])

        self.assertEqual(result["rowsSkipped"], 1)
        self.assertEqual(
            [line.patient_name for line in self.db.query(ScheduleCardActivity).all()],
            ["Clean, Patient"],
        )

    def test_rule2_omitted_lines_are_never_deactivated(self):
        self._assign_block(self.wg_or, time(12, 0), time(17, 0))
        first = stage_reviewed_rows(
            self.db, external_fax_id=191, source_label="test", surgeon_scope=["JF"],
            rows=[self._row("Kept, Patient"), self._row("Misread, Patient")],
        )
        self.db.commit()
        apply_staged_snapshot(self.db, source_fax_id=191, run_id=first["runId"])
        self.assertEqual(self.db.query(FaxIngestRow).filter_by(run_id=first["runId"]).count(), 0)

        second = stage_reviewed_rows(
            self.db, external_fax_id=191, source_label="test", surgeon_scope=["JF"],
            rows=[self._row("Kept, Patient")],
        )
        self.db.commit()
        self.assertGreater(self.db.query(FaxIngestRow).filter_by(run_id=second["runId"]).count(), 0)
        apply_staged_snapshot(self.db, source_fax_id=191, run_id=second["runId"])

        active_after_first_omission = {
            row.patient_name: row.is_active
            for row in self.db.query(ScheduleCardActivity).filter_by(activity_type="surgical").all()
        }
        self.assertTrue(active_after_first_omission["Misread, Patient"])

        third = stage_reviewed_rows(
            self.db, external_fax_id=191, source_label="test", surgeon_scope=["JF"],
            rows=[self._row("Kept, Patient")],
        )
        self.db.commit()
        apply_staged_snapshot(self.db, source_fax_id=191, run_id=third["runId"])

        lines = self.db.query(ScheduleCardActivity).filter_by(activity_type="surgical").all()
        active = {row.patient_name: row.is_active for row in lines}
        self.assertEqual(active, {"Kept, Patient": True, "Misread, Patient": True})
        self.assertEqual({row.source_fax_id for row in lines}, {191})
        self.assertEqual(self.db.query(FaxIngestRow).filter_by(run_id=third["runId"]).count(), 0)

    def test_older_fax_cannot_be_applied_after_a_newer_one(self):
        self._assign_block(self.wg_or, time(12, 0), time(17, 0))
        newer = stage_reviewed_rows(
            self.db, external_fax_id=192, source_label="test", surgeon_scope=["JF"], rows=[self._row("New, Patient")],
        )
        self.db.commit()
        apply_staged_snapshot(self.db, source_fax_id=192, run_id=newer["runId"])
        older = stage_reviewed_rows(
            self.db, external_fax_id=191, source_label="test", surgeon_scope=["JF"], rows=[self._row("Old, Patient")],
        )
        self.db.commit()
        with self.assertRaisesRegex(ValueError, "newer fax was already applied"):
            apply_staged_snapshot(self.db, source_fax_id=191, run_id=older["runId"])

    def test_source_received_time_not_desk_id_controls_fax_order(self):
        self._assign_block(self.wg_or, time(12, 0), time(17, 0))
        older = stage_reviewed_rows(
            self.db, external_fax_id=319, source_label="test", surgeon_scope=["JF"],
            source_received_at=datetime(2026, 10, 14, 20, 59),
            rows=[self._row("Old, Patient")],
        )
        self.db.commit()
        apply_staged_snapshot(self.db, source_fax_id=319, run_id=older["runId"])
        newer = stage_reviewed_rows(
            self.db, external_fax_id=316, source_label="test", surgeon_scope=["JF"],
            source_received_at=datetime(2026, 10, 15, 21, 26),
            rows=[self._row("New, Patient")],
        )
        self.db.commit()

        result = apply_staged_snapshot(self.db, source_fax_id=316, run_id=newer["runId"])

        self.assertTrue(result["ok"])

    def test_older_fax_is_allowed_when_newer_coverage_does_not_overlap(self):
        self._assign_block(self.wg_or, time(12, 0), time(17, 0))
        newer = stage_reviewed_rows(
            self.db, external_fax_id=192, source_label="test", surgeon_scope=["JF"],
            rows=[self._row("Newer Day, Patient")],
        )
        self.db.commit()
        apply_staged_snapshot(self.db, source_fax_id=192, run_id=newer["runId"])

        am = self.db.query(ScheduleCard).filter_by(session="am").one()
        self.db.add(ScheduleCard(
            week_id=am.week_id,
            surgeon_id=self.surgeon.id,
            date=date(2026, 9, 23),
            session="pm",
            baseline_state="na",
            effective_state="na",
            source="master",
        ))
        self.db.commit()
        self._assign_block(self.wg_or, time(12, 0), time(17, 0), day=date(2026, 9, 23))
        older = stage_reviewed_rows(
            self.db, external_fax_id=191, source_label="test", surgeon_scope=["JF"],
            rows=[self._row("Older Nonoverlap, Patient", day=date(2026, 9, 23))],
        )
        self.db.commit()

        result = apply_staged_snapshot(self.db, source_fax_id=191, run_id=older["runId"])
        self.assertTrue(result["ok"])

    def test_row_without_existing_am_pm_slot_is_skipped_not_fatal(self):
        self._assign_block(self.wg_or, time(12, 0), time(17, 0))
        staged = stage_reviewed_rows(
            self.db,
            external_fax_id=191,
            source_label="test",
            surgeon_scope=["JF"],
            rows=[self._row("Clean, Patient"), self._row("No Slot, Patient", day=date(2026, 9, 23))],
        )
        self.db.commit()

        result = apply_staged_snapshot(self.db, source_fax_id=191, run_id=staged["runId"])

        self.assertEqual(result["rowsSkipped"], 1)
        self.assertEqual(self.db.query(ScheduleCard).count(), 2)
        self.assertEqual(
            [line.patient_name for line in self.db.query(ScheduleCardActivity).all()],
            ["Clean, Patient"],
        )

    def _shared_line(self, initials, name):
        return ReviewedFaxRow(
            page=2,
            surgeon_initials=initials,
            surgeon_name=name,
            case_date=date(2026, 9, 22),
            start_time=time(13, 0),
            row_type="surgical",
            room="WGD S07",
            patient_name="Shared, Case",
            procedure="Shared procedure",
        )

    def _add_cj(self):
        assistant = Surgeon(
            first_name="Chris",
            last_name="Johnson",
            email="cj@example.com",
            is_active=True,
        )
        self.db.add(assistant)
        self.db.flush()
        week = ScheduleCardWeek(
            surgeon_id=assistant.id,
            week_start=date(2026, 9, 21),
            master_revision="test",
        )
        self.db.add(week)
        self.db.flush()
        self.db.add(ScheduleCard(
            week_id=week.id,
            surgeon_id=assistant.id,
            date=date(2026, 9, 22),
            session="pm",
            baseline_state="na",
            effective_state="na",
            source="master",
        ))
        self.db.commit()
        return assistant

    def _stage_shared_case(self):
        self._assign_block(self.wg_or, time(12, 0), time(17, 0))
        staged = stage_reviewed_rows(
            self.db,
            external_fax_id=193,
            source_label="test",
            surgeon_scope=["JF", "CJ"],
            rows=[
                self._shared_line("JF", "Jorge Florin"),
                self._shared_line("CJ", "Chris Johnson"),
            ],
        )
        self.db.commit()
        return staged

    def _assert_each_named_line_fills_its_card(self, result, assistant):
        self.assertEqual(result["assistedCases"], 0)
        self.assertEqual(result["surgicalCreated"], 2)
        self.assertEqual(result["cardsCreated"], 0)
        self.assertEqual(self.db.query(ScheduleCard).count(), 3)
        activities = self.db.query(ScheduleCardActivity).filter_by(activity_type="surgical", is_active=True).all()
        self.assertEqual({row.surgeon_id for row in activities}, {self.surgeon.id, assistant.id})
        cards = {card.id: card for card in self.db.query(ScheduleCard)}
        for activity in activities:
            card = cards[activity.schedule_card_id]
            self.assertEqual((card.surgeon_id, card.date, card.session), (activity.surgeon_id, date(2026, 9, 22), "pm"))
            self.assertEqual(activity.patient_name, "Shared, Case")

    def test_shared_fax_lines_fill_both_cards_when_one_surgeon_owns_the_block(self):
        assistant = self._add_cj()
        owner_pm = self.db.query(ScheduleCard).filter_by(surgeon_id=self.surgeon.id, session="pm").one()
        owner_pm.baseline_location_id = self.wg_or.id
        owner_pm.effective_location_id = self.wg_or.id
        owner_pm.baseline_state = "assigned"
        owner_pm.effective_state = "assigned"
        self.db.commit()
        staged = self._stage_shared_case()

        result = apply_staged_snapshot(self.db, source_fax_id=193, run_id=staged["runId"])

        self._assert_each_named_line_fills_its_card(result, assistant)
        owner_pm = self.db.query(ScheduleCard).filter_by(surgeon_id=self.surgeon.id, session="pm").one()
        self.assertEqual(owner_pm.baseline_state, "assigned")
        self.assertEqual(owner_pm.effective_location_id, self.wg_or.id)

    def test_co_surgeon_pair_does_not_collapse_two_fax_lines(self):
        assistant = self._add_cj()
        self.db.add(CoSurgeonPair(
            primary_surgeon_id=self.surgeon.id,
            assisting_surgeon_id=assistant.id,
            is_active=True,
        ))
        self.db.commit()
        staged = self._stage_shared_case()

        result = apply_staged_snapshot(self.db, source_fax_id=193, run_id=staged["runId"])

        self._assert_each_named_line_fills_its_card(result, assistant)
        self.assertEqual(self.db.query(CoSurgeonPair).count(), 1)

    def test_phone_reads_the_same_card_line_as_the_portal(self):
        self._assign_block(self.wg_or, time(12, 0), time(17, 0))
        staged = stage_reviewed_rows(
            self.db,
            external_fax_id=191,
            source_label="test",
            surgeon_scope=["JF"],
            rows=[self._row("Case, Patient")],
        )
        self.db.commit()
        apply_staged_snapshot(self.db, source_fax_id=191, run_id=staged["runId"])

        days = empty_days(date(2026, 9, 22), date(2026, 9, 22))
        by_date = {day["date"]: day for day in days}
        append_native_schedule(self.db, self.surgeon.id, date(2026, 9, 22), date(2026, 9, 22), by_date)
        items = by_date["2026-09-22"]["items"]
        pm = self.db.query(ScheduleCard).filter_by(session="pm").one()
        surgery = next(item for item in items if item["type"] == "surgery")
        card = next(item for item in items if item["id"] == f"card-{pm.id}")
        self.assertEqual(surgery["title"], "Case, Patient")
        self.assertEqual(surgery["cardId"], pm.id)
        self.assertEqual(card["caseCount"], 1)

    def test_both_na_blocks_each_receive_their_fax_line(self):
        assistant = self._add_cj()
        staged = self._stage_shared_case()

        result = apply_staged_snapshot(self.db, source_fax_id=193, run_id=staged["runId"])

        self._assert_each_named_line_fills_its_card(result, assistant)
        na_cards = self.db.query(ScheduleCard).filter_by(session="pm").all()
        self.assertEqual({card.baseline_state for card in na_cards}, {"na"})

    def test_send_saves_the_line_photo_and_restore_puts_it_back(self):
        self._assign_block(self.wg_or, time(12, 0), time(17, 0))
        prior_fax = FaxDocument(external_fax_id=190, source_label="test", status="applied")
        self.db.add(prior_fax)
        self.db.flush()
        prior_run = FaxIngestRun(
            fax_document_id=prior_fax.id,
            engine_version="test",
            status="applied",
            surgeon_scope_json='["JF"]',
        )
        self.db.add(prior_run)
        self.db.flush()
        prior_row = FaxIngestRow(
            run_id=prior_run.id,
            page_number=1,
            surgeon_id=self.surgeon.id,
            surgeon_initials="JF",
            case_date=date(2026, 9, 22),
            start_time=time(9, 0),
            session="pm",
            row_type="surgical",
            room_text="WGD S07",
            patient_name="Before, Line",
            procedure="Earlier procedure",
            source_location_id=self.wg_or.id,
            normalized_key="before-line",
        )
        self.db.add(prior_row)
        self.db.flush()
        pm = self.db.query(ScheduleCard).filter_by(session="pm").one()
        prior = ScheduleCardActivity(
            schedule_card_id=pm.id,
            surgeon_id=self.surgeon.id,
            location_id=self.wg_or.id,
            activity_date=date(2026, 9, 22),
            session="pm",
            activity_type="surgical",
            start_time=time(9, 0),
            patient_name="Before, Line",
            procedure="Earlier procedure",
            room_text="WGD S07",
            source_system="fax",
            source_record_key="before-line",
            fax_ingest_row_id=prior_row.id,
            identity_key="before-line",
            is_active=True,
        )
        self.db.add(prior)
        self.db.commit()

        first = stage_reviewed_rows(
            self.db, external_fax_id=191, source_label="test", surgeon_scope=["JF"],
            rows=[self._row("First, Line")],
        )
        self.db.commit()
        apply_staged_snapshot(self.db, source_fax_id=191, run_id=first["runId"])

        photo = self.db.query(FaxRestoreSet).one()
        saved = self.db.query(FaxRestoreLine).one()
        self.assertEqual(saved.schedule_card_activity_id, prior.id)
        self.assertEqual(saved.patient_name, "Before, Line")
        self.assertTrue(saved.is_active)
        self.db.refresh(prior)
        self.assertTrue(prior.is_active)
        self.assertEqual(self.db.query(ScheduleCardActivity).filter_by(is_active=True).count(), 2)

        second = stage_reviewed_rows(
            self.db, external_fax_id=191, source_label="test", surgeon_scope=["JF"],
            rows=[self._row("Second, Line")],
        )
        self.db.commit()
        apply_staged_snapshot(self.db, source_fax_id=191, run_id=second["runId"])

        self.assertEqual(self.db.query(FaxRestoreSet).count(), 1)
        saved = self.db.query(FaxRestoreLine).one()
        self.assertEqual(saved.patient_name, "Before, Line")
        self.assertTrue(saved.is_active)
        self.assertIsNone(photo.restored_at)

        result = restore_fax_snapshot(self.db, source_fax_id=191)
        self.assertEqual(result["linesRestored"], 1)
        self.assertGreaterEqual(result["linesTurnedOff"], 1)
        self.db.refresh(prior)
        self.assertTrue(prior.is_active)
        self.assertEqual(prior.patient_name, "Before, Line")
        self.assertEqual(prior.procedure, "Earlier procedure")
        fax_lines = self.db.query(ScheduleCardActivity).filter(ScheduleCardActivity.id != prior.id).all()
        self.assertTrue(fax_lines)
        self.assertTrue(all(line.is_active is False for line in fax_lines))
        self.db.refresh(photo)
        self.assertIsNotNone(photo.restored_at)
        document = self.db.query(FaxDocument).filter_by(external_fax_id=191).one()
        self.assertEqual(document.status, "restored")
        self.assertEqual(self.db.query(ScheduleWarning).count(), 0)
        with self.assertRaisesRegex(ValueError, "already put back"):
            restore_fax_snapshot(self.db, source_fax_id=191)

    def test_off_card_warning_points_at_that_card(self):
        am = self.db.query(ScheduleCard).filter_by(session="am").one()
        am.effective_state = "off"
        self.db.commit()
        staged = stage_reviewed_rows(
            self.db,
            external_fax_id=191,
            source_label="test",
            surgeon_scope=["JF"],
            rows=[
                ReviewedFaxRow(
                    page=2,
                    surgeon_initials="JF",
                    surgeon_name="Jorge Florin",
                    case_date=date(2026, 9, 22),
                    start_time=time(11, 0),
                    row_type="clinic",
                    room="AHMGGENSRG",
                    patient_name="Clinic, Patient",
                ),
            ],
        )
        self.db.commit()

        apply_staged_snapshot(self.db, source_fax_id=191, run_id=staged["runId"])

        warning = self.db.query(ScheduleWarning).one()
        self.assertEqual(warning.warning_code, "off_collision")
        self.assertEqual(warning.schedule_card_id, am.id)
        self.assertEqual(warning.source_fax_id, 191)
        self.assertEqual(self.db.query(ScheduleCardActivity).filter_by(is_active=True).count(), 1)
        self.db.add(ScheduleWarning(
            source_fax_id=191,
            schedule_card_id=am.id,
            warning_code="off_collision",
        ))
        with self.assertRaises(IntegrityError):
            self.db.flush()

    def test_restore_without_a_photo_refuses(self):
        with self.assertRaisesRegex(ValueError, "no calendar photo"):
            restore_fax_snapshot(self.db, source_fax_id=191)


if __name__ == "__main__":
    unittest.main()
