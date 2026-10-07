import json
import os
import unittest
from datetime import date, time
from unittest.mock import patch

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("SECRET_KEY", "test-secret")

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.fax_ingest_engine import ReviewedFaxRow, stage_reviewed_rows
from app.fax_snapshot_service import apply_staged_snapshot
from app.schedule_build_backup_service import revert_schedule_build_backup
from app.migrate_fax_ingest import create_applicable_view
from app.models import (
    Base,
    FaxDocument,
    FaxIngestRow,
    Location,
    ScheduleBuildBackup,
    ScheduleCard,
    ScheduleCardWeek,
    Surgeon,
    SurgicalCase,
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

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def test_daily_snapshot_fills_existing_cards_and_never_creates_cards(self):
        self.db.add(SurgicalCase(
            surgeon_id=self.surgeon.id,
            date=date(2026, 9, 22),
            start_time=time(9, 0),
            patient_name="Old, Patient",
            procedure="Old fax case",
            location_id=self.wg_or.id,
            room_text="WGD S07",
            status="scheduled",
            notes="Fax 190 daily snapshot.",
        ))
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
        cases = self.db.query(SurgicalCase).order_by(SurgicalCase.patient_name).all()
        self.assertEqual(len(cases), 2)
        self.assertEqual(next(row for row in cases if row.patient_name == "Old, Patient").status, "cancelled")
        self.assertEqual(next(row for row in cases if row.patient_name == "Case, Patient").status, "scheduled")
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
        restored_cases = self.db.query(SurgicalCase).all()
        self.assertEqual(len(restored_cases), 1)
        self.assertEqual(restored_cases[0].patient_name, "Old, Patient")
        self.assertEqual(restored_cases[0].status, "scheduled")

    def test_daily_snapshot_updates_expanded_patient_name_without_duplicate(self):
        self.db.add(SurgicalCase(
            surgeon_id=self.surgeon.id,
            date=date(2026, 9, 22),
            start_time=time(9, 0),
            patient_name="Williams, Robert",
            procedure="Prior procedure",
            location_id=self.wg_or.id,
            room_text="WGD S07",
            status="scheduled",
            notes="Fax 190 daily snapshot.",
        ))
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

        self.assertEqual(result["surgicalCreated"], 0)
        self.assertEqual(result["surgicalUpdated"], 1)
        self.assertEqual(result["surgicalCancelled"], 0)
        cases = self.db.query(SurgicalCase).all()
        self.assertEqual(len(cases), 1)
        self.assertEqual(cases[0].patient_name, "Williams, Robert Alexander")
        self.assertEqual(cases[0].procedure, "Current procedure")

    def test_daily_snapshot_keeps_mixed_facilities_on_one_session_card(self):
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

        cases = self.db.query(SurgicalCase).order_by(SurgicalCase.start_time).all()
        self.assertEqual(self.db.query(ScheduleCard).count(), 2)
        self.assertEqual([case.location_id for case in cases], [self.wg_or.id, self.alt_or.id])
        self.assertTrue(any(item["code"] == "mixed_facilities_in_session" for item in result["baselineConflicts"]))

    def test_validated_session_wins_when_case_location_matches_other_card(self):
        pm_card = self.db.query(ScheduleCard).filter_by(session="pm").one()
        wg_or_id = self.wg_or.id
        pm_card.baseline_location_id = wg_or_id
        pm_card.effective_location_id = wg_or_id
        pm_card.baseline_state = "assigned"
        pm_card.effective_state = "assigned"
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

        apply_staged_snapshot(self.db, source_fax_id=191, run_id=staged["runId"])

        cases = self.db.query(SurgicalCase).order_by(SurgicalCase.start_time).all()
        am_card = self.db.query(ScheduleCard).filter_by(session="am").one()
        self.assertEqual([case.schedule_card_id for case in cases], [am_card.id, am_card.id])
        self.assertEqual([case.location_id for case in cases], [self.alt_or.id, self.wg_or.id])

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
        self.assertEqual(self.db.query(SurgicalCase).filter_by(status="scheduled").count(), 1)

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
        self.assertEqual([case.patient_name for case in self.db.query(SurgicalCase).all()], ["Clean, Patient"])

    def test_corrected_rerun_of_the_latest_applied_fax_moves_and_cancels_its_cases(self):
        first = stage_reviewed_rows(
            self.db, external_fax_id=191, source_label="test", surgeon_scope=["JF"],
            rows=[self._row("Kept, Patient"), self._row("Misread, Patient")],
        )
        self.db.commit()
        apply_staged_snapshot(self.db, source_fax_id=191, run_id=first["runId"])

        second = stage_reviewed_rows(
            self.db, external_fax_id=191, source_label="test", surgeon_scope=["JF"],
            rows=[self._row("Kept, Patient")],
        )
        self.db.commit()
        apply_staged_snapshot(self.db, source_fax_id=191, run_id=second["runId"])

        statuses = {case.patient_name: case.status for case in self.db.query(SurgicalCase).all()}
        self.assertEqual(statuses, {"Kept, Patient": "scheduled", "Misread, Patient": "cancelled"})

    def test_older_fax_cannot_be_applied_after_a_newer_one(self):
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

    def test_row_without_existing_am_pm_slot_is_skipped_not_fatal(self):
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
        self.assertEqual([case.patient_name for case in self.db.query(SurgicalCase).all()], ["Clean, Patient"])


if __name__ == "__main__":
    unittest.main()
