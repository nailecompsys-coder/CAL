"""MRN is stored on the fax line and never changes placement, holds, or flags."""

import os
import unittest
from datetime import date, datetime, time, timedelta
from pathlib import Path

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("SECRET_KEY", "test-secret")

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.fax_card_fill import _STATEMENTS as FILL_STATEMENTS
from app.fax_ingest_engine import (
    ReviewedFaxRow,
    fax_name_key,
    normalize_mrn,
    patient_name_and_mrn,
    stage_reviewed_rows,
)
from app.fax_restore_service import restore_fax_snapshot
from app.fax_snapshot_service import apply_staged_snapshot
from app.migrate_fax_ingest import create_applicable_view
from app.models import (
    AdminNotification,
    Base,
    FaxIngestCandidate,
    FaxIngestRow,
    FaxRowDecision,
    Location,
    ScheduleCard,
    ScheduleCardActivity,
    ScheduleCardWeek,
    ScheduleWarning,
    Surgeon,
)
from app.routers.api_ingest import VisualFaxRowIn, VisualScheduleBatch, ingest_visual_schedule_route

DAY = date(2026, 9, 22)  # Tuesday
APP_DIR = Path(__file__).resolve().parents[1] / "app"


class NormalizeMrnTest(unittest.TestCase):
    def test_bracketed_and_bare_digits_keep_leading_zeros(self):
        for raw in ("[00123456]", "00123456", "  [00123456]  ", "[ 00123456 ]"):
            self.assertEqual(normalize_mrn(raw), "00123456")

    def test_missing_and_garbled_are_null(self):
        samples = (
            None, "", "   ", "abc", "[abc]", "[00123456x]", "MRN [00123456]",
            "12 34", "[00123456", "00123456]", 123456, True, ["00123456"],
            "0" * 65,
        )
        for raw in samples:
            self.assertIsNone(normalize_mrn(raw), raw)

    def test_json_number_is_not_coerced_into_an_mrn(self):
        body = VisualScheduleBatch.model_validate({
            "source_fax_id": 162,
            "rows": [{
                "surgeon_initials": "JF",
                "case_date": "2099-09-16",
                "row_type": "surgical",
                "patient_name": "Alpha, Patient",
                "mrn": 123456,
            }],
        })
        self.assertIsNone(body.rows[0].mrn)

    def test_visual_payload_passes_mrn_string_through(self):
        from unittest.mock import Mock, patch

        body = VisualScheduleBatch(
            source_fax_id=162,
            rows=[VisualFaxRowIn(
                surgeon_initials="JF",
                case_date="2099-09-16",
                start_time="0715",
                row_type="surgical",
                patient_name="Alpha, Patient",
                mrn="[00123456]",
            )],
        )
        with patch("app.routers.api_ingest.stage_reviewed_rows", return_value={"writeMode": "staging_only"}) as stage:
            ingest_visual_schedule_route(body, db=Mock())
        self.assertEqual(stage.call_args.kwargs["rows"][0].mrn, "[00123456]")

    def test_bracketed_mrn_in_the_name_is_stripped_and_kept(self):
        clean, mrn = patient_name_and_mrn("Sample, Patient [00112233]", None)
        self.assertEqual((clean, mrn), ("Sample, Patient", "00112233"))
        embedded, embedded_mrn = patient_name_and_mrn("Alpha [00445566] Beta", None)
        self.assertEqual((embedded, embedded_mrn), ("Alpha Beta", "00445566"))
        self.assertEqual(
            patient_name_and_mrn("SAMPLE,  PATIENT [00112233]", None),
            ("SAMPLE, PATIENT", "00112233"),
        )

    def test_explicit_mrn_wins_and_long_or_non_digit_brackets_do_not_fill(self):
        self.assertEqual(
            patient_name_and_mrn("Sample, Patient [00112233]", "[00998877]"),
            ("Sample, Patient", "00998877"),
        )
        self.assertEqual(
            patient_name_and_mrn("Sample, Patient [00112233]", "not-an-mrn"),
            ("Sample, Patient", "00112233"),
        )
        self.assertEqual(
            patient_name_and_mrn("Sample, Patient [OR]", None),
            ("Sample, Patient [OR]", None),
        )
        self.assertEqual(
            patient_name_and_mrn("Sample, Patient [" + ("1" * 65) + "]", None)[0],
            "Sample, Patient",
        )
        self.assertIsNone(patient_name_and_mrn("Sample, Patient [" + ("1" * 65) + "]", None)[1])
        kept = "0" * 64
        self.assertEqual(patient_name_and_mrn(f"Sample, Patient [{kept}]", None)[1], kept)
        self.assertEqual(
            patient_name_and_mrn("Sample, Patient [00112233] [00445566]", None),
            ("Sample, Patient", "00445566"),
        )

    def test_name_key_matches_either_side_and_keeps_time(self):
        bracketed = fax_name_key("SAMPLE,  PATIENT [00112233]|08:00:00|surgical")
        clean = fax_name_key("Sample, Patient|08:00:00|surgical")
        embedded = fax_name_key("Alpha [00445566] Beta|08:00:00|surgical")
        self.assertEqual(bracketed, clean)
        self.assertEqual(embedded, fax_name_key("alpha beta|08:00:00|surgical"))
        self.assertNotEqual(clean, fax_name_key("Sample, Patient|09:00:00|surgical"))
        self.assertNotEqual(clean, fax_name_key("Other, Person|08:00:00|surgical"))
        self.assertNotEqual(
            fax_name_key("Sample, Patient [OR]|08:00:00|surgical"),
            clean,
        )

    def test_resolution_and_fill_normalize_both_sides(self):
        fill = (APP_DIR / "sql" / "fill_cards_from_fax.sql").read_text()
        self.assertIn("cal_fax_name_key(schedule_card_activities.identity_key)", fill)
        self.assertIn("cal_fax_name_key(activity.identity_key)", fill)
        self.assertIn("cal_fax_display_name(fax_row.patient_name)", fill)
        self.assertNotIn("identity_key = LOWER(COALESCE(fax_row.patient_name", fill)
        for name in ("resolve_fax_candidates.postgresql.sql", "resolve_fax_candidates.sqlite.sql"):
            sql = (APP_DIR / "sql" / name).read_text()
            self.assertIn(
                "cal_fax_name_key(peer.patient_name_raw) = cal_fax_name_key(l.patient_name_raw)",
                sql,
            )
            self.assertNotIn("when mrn", sql.lower())
        migration = (APP_DIR / "migrate_fax_ingest.py").read_text()
        self.assertIn("CAL_FAX_NAME_SQL", migration)


class FaxMrnTest(unittest.TestCase):
    def _world(self):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        db = sessionmaker(bind=engine)()
        surgeon = Surgeon(first_name="Jorge", last_name="Florin", email="jf@example.com", is_active=True)
        hospital = Location(name="Winter Garden OR", abbreviation="WG-OR", location_type="hospital", is_active=True)
        db.add_all([surgeon, hospital])
        db.flush()
        week = ScheduleCardWeek(surgeon_id=surgeon.id, week_start=date(2026, 9, 21), master_revision="t")
        db.add(week)
        db.flush()
        for day, state in ((DAY, "assigned"), (DAY + timedelta(days=1), "off")):
            for session in ("am", "pm"):
                db.add(ScheduleCard(
                    week_id=week.id, surgeon_id=surgeon.id, date=day, session=session,
                    baseline_state=state, effective_state=state,
                    baseline_location_id=hospital.id, effective_location_id=hospital.id,
                    source="master",
                ))
        db.commit()
        with engine.begin() as conn:
            create_applicable_view(conn)
        return engine, db

    def _row(self, patient, *, at=time(8, 0), day=DAY, flags=None, page=2, mrn=None,
             surgeon="Jorge Florin", initials="JF", procedure="first pass"):
        return ReviewedFaxRow(
            page=page, surgeon_initials=initials, surgeon_name=surgeon, case_date=day,
            start_time=at, row_type="surgical", room="WGD S07", patient_name=patient,
            procedure=procedure, extraction_flags=flags, mrn=mrn,
        )

    def _mixed_rows(self, clean_mrn=None, off_mrn=None, unknown_mrn=None):
        return [
            self._row("Clean, Patient", at=time(8, 0), mrn=clean_mrn),
            self._row("Flagged, Patient", at=time(9, 0), flags="ocr_uncertain", mrn="not-an-mrn"),
            self._row("Offday, Patient", at=time(8, 0), day=DAY + timedelta(days=1), mrn=off_mrn),
            self._row("Unknown, Patient", at=time(11, 0), page=9, surgeon="Zed Nobody", initials="ZN", mrn=unknown_mrn),
        ]

    def _decisions(self, db, run_id):
        return [
            (row.patient_name, decision.status, decision.reason_code, row.extraction_flags, row.normalized_key, row.mrn)
            for row, decision in (
                db.query(FaxIngestRow, FaxRowDecision)
                .join(FaxRowDecision, FaxRowDecision.fax_row_id == FaxIngestRow.id)
                .filter(FaxIngestRow.run_id == run_id)
                .order_by(FaxIngestRow.patient_name, FaxIngestRow.id)
                .all()
            )
        ]

    def _fingerprint(self, db, decisions, applied):
        cards = [
            (card.date, card.session, card.baseline_state, card.effective_state, card.effective_location_id)
            for card in db.query(ScheduleCard).order_by(ScheduleCard.date, ScheduleCard.session)
        ]
        lines = [
            (line.patient_name, line.identity_key, line.is_active, line.activity_type, line.session, line.procedure)
            for line in db.query(ScheduleCardActivity).order_by(ScheduleCardActivity.patient_name, ScheduleCardActivity.id)
        ]
        warnings = sorted(code for (code,) in db.query(ScheduleWarning.warning_code).all())
        comparable = [
            (patient, status, reason, flags, key)
            for patient, status, reason, flags, key, _mrn in decisions
        ]
        return {
            "decisions": comparable,
            "cards": cards,
            "lines": lines,
            "warnings": warnings,
            "applied": {
                key: applied[key]
                for key in ("cardsCreated", "cardsChanged", "notificationsSent", "linesDeactivated", "rowsSkipped")
            },
            "held": applied["report"]["heldByReason"],
            "conflicts": applied["report"]["conflictsFlagged"],
            "notifications": db.query(AdminNotification).count(),
        }

    def test_mrn_column_is_indexed_text(self):
        engine, db = self._world()
        try:
            indexed = {
                name for (name,) in db.execute(text(
                    "SELECT name FROM sqlite_master WHERE type = 'index' AND sql LIKE '%mrn%'"
                ))
            }
            self.assertIn("ix_schedule_card_activities_mrn", indexed)
            self.assertIn("ix_fax_ingest_rows_mrn", indexed)
            self.assertIn("ix_fax_ingest_candidates_mrn", indexed)
            ddl = db.execute(text(
                "SELECT sql FROM sqlite_master WHERE name = 'schedule_card_activities'"
            )).scalar()
            self.assertIn("mrn TEXT", ddl)
        finally:
            db.close()
            engine.dispose()

    def test_migration_is_additive(self):
        source = (APP_DIR / "migrate_fax_mrn.py").read_text()
        self.assertIn("ADD COLUMN IF NOT EXISTS mrn TEXT", source)
        self.assertNotIn("DROP COLUMN", source)
        self.assertNotIn("DROP TABLE", source)
        fill = next(statement for statement in FILL_STATEMENTS if "ON CONFLICT" in statement)
        self.assertIn("COALESCE(schedule_card_activities.mrn, excluded.mrn)", fill)
        self.assertNotIn("mrn = excluded.mrn", fill)
        self.assertIn("is_active IS NOT TRUE", fill)
        parked = next(statement for statement in FILL_STATEMENTS if "|inactive-" in statement)
        self.assertIn("active_line.is_active = TRUE", parked)
        self.assertNotIn("is_active = FALSE", "\n".join(FILL_STATEMENTS))
        for name in ("resolve_fax_candidates.postgresql.sql", "resolve_fax_candidates.sqlite.sql"):
            sql = (APP_DIR / "sql" / name).read_text().lower()
            self.assertNotIn("when mrn", sql)

    def test_missing_or_garbled_mrn_matches_hold_and_flag_outcome(self):
        fingerprints = []
        stored = {}
        variants = {
            "absent": (None, None, None),
            "present": ("[00123456]", "[00990099]", "[00123456]"),
            "garbled": ("room 5", "MRN [00]", "abc"),
        }
        for label, (clean_mrn, off_mrn, unknown_mrn) in variants.items():
            engine, db = self._world()
            try:
                staged = stage_reviewed_rows(
                    db, external_fax_id=191, source_label="t",
                    source_received_at=datetime(2026, 10, 1, 12, 0),
                    rows=self._mixed_rows(clean_mrn, off_mrn, unknown_mrn),
                )
                db.commit()
                decisions = self._decisions(db, staged["runId"])
                clean = db.query(FaxIngestRow).filter_by(patient_name="Clean, Patient").one()
                flagged = db.query(FaxIngestRow).filter_by(patient_name="Flagged, Patient").one()
                self.assertNotIn("00123456", clean.normalized_key)
                self.assertIsNone(clean.extraction_flags)
                self.assertEqual(flagged.extraction_flags, "ocr_uncertain")
                self.assertIsNone(flagged.mrn)
                applied = apply_staged_snapshot(db, source_fax_id=191, run_id=staged["runId"])
                fingerprints.append(self._fingerprint(db, decisions, applied))
                stored[label] = {
                    line.patient_name: line.mrn
                    for line in db.query(ScheduleCardActivity).all()
                }
                for line in db.query(ScheduleCardActivity).all():
                    self.assertNotIn("00123456", line.identity_key)
            finally:
                db.close()
                engine.dispose()

        self.assertEqual(fingerprints[0], fingerprints[1])
        self.assertEqual(fingerprints[0], fingerprints[2])
        self.assertEqual(stored["present"]["Clean, Patient"], "00123456")
        self.assertEqual(stored["present"]["Offday, Patient"], "00990099")
        self.assertIsNone(stored["absent"]["Clean, Patient"])
        self.assertIsNone(stored["garbled"]["Clean, Patient"])
        self.assertIsNone(stored["present"]["Flagged, Patient"])
        self.assertGreater(fingerprints[0]["conflicts"], 0)
        self.assertEqual(fingerprints[0]["held"], {"unknown_surgeon": 1})
        self.assertIn(("Clean, Patient", "ready", "existing_card"), [
            item[:3] for item in fingerprints[0]["decisions"]
        ])

    def test_mrn_is_stored_on_the_candidate_before_apply(self):
        engine, db = self._world()
        try:
            stage_reviewed_rows(
                db, external_fax_id=191, source_label="t",
                source_received_at=datetime(2026, 10, 1, 12, 0),
                rows=[self._row("Alpha, Patient", mrn="[00123456]")],
            )
            db.commit()
            self.assertEqual(db.query(FaxIngestCandidate).one().mrn, "00123456")
            self.assertEqual(db.query(FaxIngestRow).one().mrn, "00123456")
        finally:
            db.close()
            engine.dispose()

    def test_existing_mrn_is_filled_when_null_and_never_overwritten(self):
        engine, db = self._world()
        try:
            first = stage_reviewed_rows(
                db, external_fax_id=191, source_label="t",
                source_received_at=datetime(2026, 10, 1, 12, 0),
                rows=[
                    self._row("Alpha, Patient", at=time(8, 0), mrn="[00111111]"),
                    self._row("Bravo, Patient", at=time(9, 0), mrn=None),
                    self._row("Charlie, Patient", at=time(10, 0), mrn="[00333333]"),
                ],
            )
            db.commit()
            first_apply = apply_staged_snapshot(db, source_fax_id=191, run_id=first["runId"])
            self.assertEqual(first_apply["cardsCreated"], 0)
            self.assertEqual(first_apply["notificationsSent"], 0)
            self.assertEqual(first_apply["linesDeactivated"], 0)

            second = stage_reviewed_rows(
                db, external_fax_id=192, source_label="t",
                source_received_at=datetime(2026, 10, 2, 12, 0),
                rows=[
                    self._row("Alpha, Patient", at=time(8, 0), mrn="[00999999]", procedure="second pass"),
                    self._row("Bravo, Patient", at=time(9, 0), mrn="[00222222]", procedure="second pass"),
                    self._row("Charlie, Patient", at=time(10, 0), mrn="nope", procedure="second pass"),
                ],
            )
            db.commit()
            self.assertEqual(
                db.query(FaxIngestRow).filter_by(run_id=second["runId"], patient_name="Bravo, Patient").one().mrn,
                "00222222",
            )
            second_apply = apply_staged_snapshot(db, source_fax_id=192, run_id=second["runId"])
            self.assertEqual(second_apply["linesDeactivated"], 0)
            self.assertEqual(db.query(ScheduleCard).count(), 4)
            lines = {line.patient_name: line for line in db.query(ScheduleCardActivity).all()}
            self.assertEqual(set(lines), {"Alpha, Patient", "Bravo, Patient", "Charlie, Patient"})
            self.assertEqual(lines["Alpha, Patient"].mrn, "00111111")
            self.assertEqual(lines["Bravo, Patient"].mrn, "00222222")
            self.assertEqual(lines["Charlie, Patient"].mrn, "00333333")
            self.assertTrue(all(line.procedure == "second pass" and line.is_active for line in lines.values()))

            third = stage_reviewed_rows(
                db, external_fax_id=192, source_label="t",
                source_received_at=datetime(2026, 10, 2, 12, 0),
                rows=[
                    self._row("Alpha, Patient", at=time(8, 0), mrn="[00888888]", procedure="third pass"),
                    self._row("Bravo, Patient", at=time(9, 0), mrn=None, procedure="third pass"),
                    self._row("Charlie, Patient", at=time(10, 0), mrn="[00777777]", procedure="third pass"),
                ],
            )
            db.commit()
            apply_staged_snapshot(db, source_fax_id=192, run_id=third["runId"])
            lines = {line.patient_name: line for line in db.query(ScheduleCardActivity).all()}
            self.assertEqual(lines["Alpha, Patient"].mrn, "00111111")
            self.assertEqual(lines["Bravo, Patient"].mrn, "00222222")
            self.assertEqual(lines["Charlie, Patient"].mrn, "00333333")
            self.assertTrue(all(line.procedure == "third pass" for line in lines.values()))
            self.assertEqual(db.query(AdminNotification).count(), 0)
        finally:
            db.close()
            engine.dispose()

    def test_restore_puts_back_the_mrn_from_the_photo(self):
        engine, db = self._world()
        try:
            first = stage_reviewed_rows(
                db, external_fax_id=191, source_label="t",
                source_received_at=datetime(2026, 10, 1, 12, 0),
                rows=[self._row("Alpha, Patient", mrn=None, procedure="first pass")],
            )
            db.commit()
            apply_staged_snapshot(db, source_fax_id=191, run_id=first["runId"])
            second = stage_reviewed_rows(
                db, external_fax_id=192, source_label="t",
                source_received_at=datetime(2026, 10, 2, 12, 0),
                rows=[self._row("Alpha, Patient", mrn="[00444444]", procedure="second pass")],
            )
            db.commit()
            apply_staged_snapshot(db, source_fax_id=192, run_id=second["runId"])
            self.assertEqual(db.query(ScheduleCardActivity).one().mrn, "00444444")

            restore_fax_snapshot(db, source_fax_id=192)
            line = db.query(ScheduleCardActivity).one()
            self.assertEqual(line.procedure, "first pass")
            self.assertIsNone(line.mrn)
            self.assertTrue(line.is_active)
        finally:
            db.close()
            engine.dispose()


    def _seed_prior_line(self, db, patient_name, *, identity_key, mrn=None, fax_id=190, at=time(8, 0),
                         source_record_key=None, is_active=True, procedure="prior pass"):
        card = db.query(ScheduleCard).filter_by(date=DAY, session="am").one()
        surgeon = db.query(Surgeon).one()
        line = ScheduleCardActivity(
            schedule_card_id=card.id,
            surgeon_id=surgeon.id,
            location_id=card.effective_location_id,
            activity_date=DAY,
            session="am",
            activity_type="surgical",
            start_time=at,
            patient_name=patient_name,
            mrn=mrn,
            procedure=procedure,
            source_system="fax",
            source_record_key=source_record_key or f"{fax_id}|prior",
            source_fax_id=fax_id,
            identity_key=identity_key,
            is_active=is_active,
        )
        db.add(line)
        db.commit()
        return line.id

    def _apply_one(self, db, patient, *, mrn=None, fax=191):
        staged = stage_reviewed_rows(
            db, external_fax_id=fax, source_label="t",
            source_received_at=datetime(2026, 10, 2, 12, 0),
            rows=[self._row(patient, mrn=mrn, procedure="second pass")],
        )
        db.commit()
        row = db.query(FaxIngestRow).filter_by(run_id=staged["runId"]).one()
        decision = db.query(FaxRowDecision).filter_by(fax_row_id=row.id).one()
        staged_fact = (row.patient_name, row.mrn, row.extraction_flags, decision.status, decision.reason_code)
        apply_staged_snapshot(db, source_fax_id=fax, run_id=staged["runId"])
        return staged_fact

    def test_bracketed_existing_line_matches_clean_incoming(self):
        engine, db = self._world()
        try:
            prior_id = self._seed_prior_line(
                db,
                "SAMPLE,  PATIENT [00112233]",
                identity_key="sample,  patient [00112233]|08:00:00|surgical",
            )
            patient, mrn, flags, status, reason = self._apply_one(db, "Sample, Patient")
            self.assertEqual(patient, "Sample, Patient")
            self.assertIsNone(mrn)
            self.assertIsNone(flags)
            self.assertEqual((status, reason), ("ready", "existing_card"))
            lines = db.query(ScheduleCardActivity).all()
            self.assertEqual(len(lines), 1)
            line = lines[0]
            self.assertEqual(line.id, prior_id)
            self.assertEqual(line.patient_name, "Sample, Patient")
            self.assertNotIn("[", line.patient_name)
            self.assertNotIn("00112233", line.identity_key)
            self.assertIsNone(line.mrn)
            self.assertEqual(line.procedure, "second pass")
            self.assertEqual(line.source_fax_id, 191)
            self.assertTrue(line.is_active)
        finally:
            db.close()
            engine.dispose()

    def test_clean_existing_line_matches_bracketed_incoming(self):
        engine, db = self._world()
        try:
            prior_id = self._seed_prior_line(
                db,
                "Alpha Beta",
                identity_key="alpha beta|08:00:00|surgical",
            )
            patient, mrn, flags, status, reason = self._apply_one(db, "Alpha [00445566] Beta")
            self.assertEqual(patient, "Alpha Beta")
            self.assertEqual(mrn, "00445566")
            self.assertIsNone(flags)
            self.assertEqual((status, reason), ("ready", "existing_card"))
            candidate = db.query(FaxIngestCandidate).filter_by(patient_name_raw="Alpha Beta").one()
            self.assertEqual(candidate.mrn, "00445566")
            lines = db.query(ScheduleCardActivity).all()
            self.assertEqual(len(lines), 1)
            line = lines[0]
            self.assertEqual(line.id, prior_id)
            self.assertEqual(line.patient_name, "Alpha Beta")
            self.assertNotIn("[", line.patient_name)
            self.assertNotIn("00445566", line.identity_key)
            self.assertEqual(line.mrn, "00445566")
            self.assertEqual(line.procedure, "second pass")
            self.assertEqual(line.source_fax_id, 191)
        finally:
            db.close()
            engine.dispose()

    def test_bracketed_incoming_name_does_not_overwrite_an_existing_mrn(self):
        engine, db = self._world()
        try:
            prior_id = self._seed_prior_line(
                db,
                "Sample, Patient",
                identity_key="sample, patient|08:00:00|surgical",
                mrn="00998877",
            )
            patient, mrn, flags, status, _reason = self._apply_one(db, "Sample, Patient [00112233]")
            self.assertEqual(patient, "Sample, Patient")
            self.assertEqual(mrn, "00112233")
            self.assertEqual(status, "ready")
            self.assertIsNone(flags)
            line = db.query(ScheduleCardActivity).one()
            self.assertEqual(line.id, prior_id)
            self.assertEqual(line.patient_name, "Sample, Patient")
            self.assertEqual(line.mrn, "00998877")
        finally:
            db.close()
            engine.dispose()

    def test_a_different_patient_is_still_a_new_line(self):
        engine, db = self._world()
        try:
            prior_id = self._seed_prior_line(
                db,
                "Sample, Patient",
                identity_key="sample, patient|08:00:00|surgical",
            )
            self._apply_one(db, "Other, Person")
            lines = {line.patient_name: line for line in db.query(ScheduleCardActivity).all()}
            self.assertEqual(set(lines), {"Sample, Patient", "Other, Person"})
            self.assertEqual(lines["Sample, Patient"].id, prior_id)
            self.assertEqual(lines["Sample, Patient"].procedure, "prior pass")
            self.assertEqual(lines["Sample, Patient"].source_fax_id, 190)
            self.assertEqual(lines["Other, Person"].source_fax_id, 191)
        finally:
            db.close()
            engine.dispose()

    def _plant_inactive_twin(self, db, *, run_id, active_mrn=None):
        """Inactive bracketed copy already owns the incoming source key."""
        fax_row = db.query(FaxIngestRow).filter_by(run_id=run_id).one()
        incoming_key = f"191|{fax_row.normalized_key}"
        active_id = self._seed_prior_line(
            db,
            "Sample, Patient",
            identity_key="sample, patient|08:00:00|surgical",
            mrn=active_mrn,
            procedure="prior pass",
        )
        inactive_id = self._seed_prior_line(
            db,
            "Sample, Patient [00990011]",
            identity_key="sample, patient [00990011]|08:00:00|surgical",
            mrn="00990011",
            fax_id=188,
            source_record_key=incoming_key,
            is_active=False,
            procedure="bracketed copy",
        )
        return active_id, inactive_id, incoming_key

    def test_inactive_bracketed_copy_is_not_reactivated(self):
        engine, db = self._world()
        try:
            staged = stage_reviewed_rows(
                db, external_fax_id=191, source_label="t",
                source_received_at=datetime(2026, 10, 2, 12, 0),
                rows=[self._row("Sample, Patient [00112233]", procedure="second pass")],
            )
            db.commit()
            fax_row = db.query(FaxIngestRow).filter_by(run_id=staged["runId"]).one()
            self.assertEqual(fax_row.patient_name, "Sample, Patient")
            self.assertEqual(fax_row.mrn, "00112233")
            self.assertIsNone(fax_row.extraction_flags)
            active_id, inactive_id, incoming_key = self._plant_inactive_twin(db, run_id=staged["runId"])
            result = apply_staged_snapshot(db, source_fax_id=191, run_id=staged["runId"])
            lines = {line.id: line for line in db.query(ScheduleCardActivity).order_by(ScheduleCardActivity.id)}
            self.assertEqual(set(lines), {active_id, inactive_id})
            self.assertEqual(result["surgicalCreated"], 0)
            self.assertEqual(result["linesDeactivated"], 0)
            active = lines[active_id]
            inactive = lines[inactive_id]
            self.assertTrue(active.is_active)
            self.assertEqual(active.patient_name, "Sample, Patient")
            self.assertNotIn("[", active.patient_name)
            self.assertEqual(active.procedure, "second pass")
            self.assertEqual(active.mrn, "00112233")
            self.assertEqual(active.source_fax_id, 191)
            self.assertEqual(active.source_record_key, incoming_key)
            self.assertFalse(inactive.is_active)
            self.assertEqual(inactive.patient_name, "Sample, Patient [00990011]")
            self.assertEqual(inactive.procedure, "bracketed copy")
            self.assertEqual(inactive.mrn, "00990011")
            self.assertNotEqual(inactive.source_record_key, incoming_key)
            self.assertIn("|inactive-", inactive.source_record_key)
        finally:
            db.close()
            engine.dispose()

    def test_active_twin_keeps_its_mrn_when_duplicate_is_inactive(self):
        engine, db = self._world()
        try:
            staged = stage_reviewed_rows(
                db, external_fax_id=191, source_label="t",
                source_received_at=datetime(2026, 10, 2, 12, 0),
                rows=[self._row("Sample, Patient [00112233]", procedure="second pass")],
            )
            db.commit()
            active_id, inactive_id, incoming_key = self._plant_inactive_twin(
                db, run_id=staged["runId"], active_mrn="00998877",
            )
            apply_staged_snapshot(db, source_fax_id=191, run_id=staged["runId"])
            lines = {line.id: line for line in db.query(ScheduleCardActivity).all()}
            self.assertEqual(set(lines), {active_id, inactive_id})
            self.assertEqual(lines[active_id].mrn, "00998877")
            self.assertEqual(lines[active_id].procedure, "second pass")
            self.assertTrue(lines[active_id].is_active)
            self.assertEqual(lines[active_id].source_record_key, incoming_key)
            self.assertFalse(lines[inactive_id].is_active)
            self.assertEqual(lines[inactive_id].mrn, "00990011")
        finally:
            db.close()
            engine.dispose()


if __name__ == "__main__":
    unittest.main()
