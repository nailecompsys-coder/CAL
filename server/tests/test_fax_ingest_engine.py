import os
import unittest
from datetime import date, time

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("SECRET_KEY", "test-secret")

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.fax_ingest_engine import ReviewedFaxRow, stage_reviewed_rows
from app.migrate_fax_ingest import create_applicable_view
from app.models import (
    Base,
    FaxIngestRow,
    FaxIngestCandidate,
    FaxIngestCoverage,
    FaxRowDecision,
    Location,
    ORBlockAssignment,
    ORBlockInstance,
    ScheduleCard,
    ScheduleCardWeek,
    Surgeon,
)


class FaxIngestEngineTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        with self.engine.begin() as conn:
            create_applicable_view(conn)
        self.Session = sessionmaker(bind=self.engine)
        self.db = self.Session()
        self.surgeon = Surgeon(first_name="Jorge", last_name="Florin", is_active=True, staff_type="physician")
        self.location = Location(name="Minneola OR", abbreviation="MN-OR", location_type="hospital", is_active=True)
        self.ap_location = Location(name="Apopka OR", abbreviation="AP-OR", location_type="hospital", is_active=True)
        self.db.add_all([self.surgeon, self.location, self.ap_location])
        self.db.flush()
        week = ScheduleCardWeek(surgeon_id=self.surgeon.id, week_start=date(2026, 9, 14))
        self.db.add(week)
        self.db.flush()
        for offset in range(5):
            for session in ("am", "pm"):
                self.db.add(ScheduleCard(
                    week_id=week.id, surgeon_id=self.surgeon.id, date=date(2026, 9, 14 + offset), session=session,
                    baseline_state="assigned" if (offset, session) == (2, "am") else "na",
                    effective_state="assigned" if (offset, session) == (2, "am") else "na",
                    baseline_location_id=self.location.id if (offset, session) == (2, "am") else None,
                    effective_location_id=self.location.id if (offset, session) == (2, "am") else None,
                ))
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def _block(self, location, start, end, day=date(2026, 9, 16)):
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
        return block

    def row(self, **changes):
        values = dict(page=2, surgeon_initials="JF", surgeon_name="Jorge Florin", case_date=date(2026, 9, 16), start_time=time(7, 15), row_type="surgical", room="MIN S05", patient_name="White, Jeffrey", procedure="Robotic repair")
        values.update(changes)
        return ReviewedFaxRow(**values)

    def test_staging_resolves_existing_card_without_creating_schedule_data(self):
        result = stage_reviewed_rows(self.db, external_fax_id=168, source_label="Fax 168", rows=[self.row()])
        self.db.commit()
        decision = self.db.query(FaxRowDecision).one()
        self.assertEqual(result["writeMode"], "staging_only")
        self.assertEqual(decision.status, "ready")
        self.assertEqual(decision.reason_code, "existing_card")
        self.assertEqual(self.db.query(FaxIngestRow).count(), 1)
        self.assertEqual(self.db.query(ScheduleCard).count(), 10)

    def test_mixed_numbered_and_unnumbered_rows_never_collide(self):
        # Regression: Desk faxes #334/#339/#343/#348 mixed explicit and missing
        # row numbers on one page; the auto-number hit an explicit one and the
        # whole fax failed with a unique violation.
        rows = [
            self.row(source_row_number=1, patient_name="A, One"),
            self.row(source_row_number=None, patient_name="B, Two", start_time=time(8, 0)),
            self.row(source_row_number=2, patient_name="C, Three", start_time=time(9, 0)),
            self.row(source_row_number=2, patient_name="D, Four", start_time=time(10, 0)),
            self.row(page=3, source_row_number=None, patient_name="E, Five"),
            self.row(page=3, source_row_number=7, patient_name="F, Six", start_time=time(8, 0)),
        ]
        stage_reviewed_rows(self.db, external_fax_id=334, source_label="Fax 334", rows=rows)
        self.db.commit()
        candidates = self.db.query(FaxIngestCandidate).order_by(FaxIngestCandidate.id).all()
        self.assertEqual([(c.page_number, c.source_row_number) for c in candidates], [(2, 1), (2, 2), (2, 3), (2, 4), (3, 1), (3, 2)])
        self.assertEqual(
            [c.evidence_ref for c in candidates],
            ["page:2:row:1:desk_row:1", "page:2:row:2:desk_row:none", "page:2:row:3:desk_row:2",
             "page:2:row:4:desk_row:2", "page:3:row:1:desk_row:none", "page:3:row:2:desk_row:7"],
        )
        self.assertEqual(self.db.query(FaxIngestRow).count(), 6)
        self.assertEqual(self.db.query(ScheduleCard).count(), 10)

    def test_invalid_date_is_retained_as_unresolved_candidate(self):
        result = stage_reviewed_rows(
            self.db,
            external_fax_id=169,
            source_label="Fax 169",
            rows=[self.row(case_date="", surgeon_initials="", surgeon_name=None,
                           start_time=None, patient_name="", extraction_flags="bad_date")],
        )
        self.db.commit()
        self.assertEqual(result["rows"], 1)
        self.assertEqual(result["materializedRows"], 0)
        self.assertEqual(result["decisions"], {"unresolved": 1})
        self.assertEqual(self.db.query(FaxIngestCandidate).count(), 1)
        self.assertEqual(self.db.query(FaxIngestRow).count(), 0)

    def test_unresolved_ocr_date_does_not_expand_authoritative_coverage(self):
        result = stage_reviewed_rows(
            self.db,
            external_fax_id=169,
            source_label="Fax 169",
            coverage=[("JF", date(2026, 9, 16)), ("JF", date(2034, 5, 21))],
            rows=[
                self.row(),
                self.row(case_date=date(2034, 5, 21), patient_name="Bad Date", extraction_flags="bad_date"),
            ],
        )
        self.db.commit()

        self.assertEqual(result["decisions"], {"ready": 1, "unresolved": 1})
        self.assertEqual(
            [(row.surgeon_id, row.case_date) for row in self.db.query(FaxIngestCoverage).all()],
            [(self.surgeon.id, date(2026, 9, 16))],
        )

    def test_generic_room_on_na_is_reviewed_not_assigned(self):
        result = stage_reviewed_rows(self.db, external_fax_id=169, source_label="Fax 169", rows=[self.row(start_time=time(13, 30), room="AHMGGENSRG")])
        self.db.commit()
        decision = self.db.query(FaxRowDecision).one()
        self.assertEqual(result["decisions"], {"unresolved": 1})
        self.assertEqual(decision.reason_code, "no_block_for_facility")
        self.assertIsNone(decision.schedule_card.effective_location_id)

    def test_placeholder_room_uses_the_block_not_an_earlier_room(self):
        self._block(self.ap_location, time(12, 0), time(17, 0))
        result = stage_reviewed_rows(
            self.db,
            external_fax_id=171,
            source_label="Fax 171",
            rows=[
                self.row(start_time=time(9, 15), room="APK S03"),
                self.row(start_time=time(13, 20), room="AHMGGENSRG", patient_name="Second, Patient"),
                self.row(start_time=time(14, 0), room="AHMGGENSRG", patient_name="Third, Patient"),
            ],
        )
        self.db.commit()
        decisions = self.db.query(FaxRowDecision).order_by(FaxRowDecision.id).all()
        staged = self.db.query(FaxIngestRow).order_by(FaxIngestRow.id).all()
        self.assertEqual(result["decisions"], {"ready": 3})
        self.assertEqual(decisions[0].reason_code, "existing_card")
        self.assertEqual(staged[0].source_location_id, self.location.id)
        self.assertEqual([decision.reason_code for decision in decisions[1:]], ["block_location", "block_location"])
        self.assertEqual({row.source_location_id for row in staged[1:]}, {self.ap_location.id})

    def test_rule7_block_disagreeing_with_card_is_held(self):
        self._block(self.ap_location, time(7, 0), time(12, 0))
        result = stage_reviewed_rows(
            self.db,
            external_fax_id=172,
            source_label="Fax 172",
            rows=[self.row(room="MIN S05")],
        )
        self.db.commit()
        decision = self.db.query(FaxRowDecision).one()
        self.assertEqual(result["decisions"], {"unresolved": 1})
        self.assertEqual(decision.reason_code, "location_conflict")

    def test_generic_rows_follow_explicit_same_session_epic_location(self):
        self._block(self.ap_location, time(12, 0), time(17, 0))
        result = stage_reviewed_rows(
            self.db,
            external_fax_id=173,
            source_label="Fax 173",
            rows=[
                self.row(start_time=time(13, 10), room="MIN S99"),
                self.row(start_time=time(13, 30), room="AHMGGENSRG", patient_name="Second, Patient"),
            ],
        )
        self.db.commit()
        staged = self.db.query(FaxIngestRow).order_by(FaxIngestRow.id).all()
        self.assertEqual(result["decisions"], {"ready": 2})
        self.assertEqual({row.source_location_id for row in staged}, {self.ap_location.id})

    def test_off_card_is_flagged_but_never_removed(self):
        card = self.db.query(ScheduleCard).filter_by(surgeon_id=self.surgeon.id, date=date(2026, 9, 16), session="am").one()
        card.effective_state = "off"
        self.db.commit()
        stage_reviewed_rows(self.db, external_fax_id=170, source_label="Fax 170", rows=[self.row()])
        self.db.commit()
        decision = self.db.query(FaxRowDecision).one()
        self.assertEqual(decision.reason_code, "off_collision")
        self.assertEqual(self.db.query(ScheduleCard).count(), 10)

    def test_off_does_not_make_an_unresolved_location_safe_to_apply(self):
        card = self.db.query(ScheduleCard).filter_by(
            surgeon_id=self.surgeon.id, date=date(2026, 9, 16), session="pm"
        ).one()
        card.effective_state = "off"
        self.db.commit()

        result = stage_reviewed_rows(
            self.db,
            external_fax_id=176,
            source_label="Fax 176",
            rows=[self.row(start_time=time(13, 30), room="AHMGGENSRG")],
        )
        self.db.commit()

        decision = self.db.query(FaxRowDecision).one()
        self.assertEqual(result["decisions"], {"unresolved": 1})
        self.assertEqual(decision.reason_code, "no_block_for_facility")

    def test_rule8_unknown_room_takes_location_and_type_from_assigned_card(self):
        stage_reviewed_rows(self.db, external_fax_id=170, source_label="Fax 170", rows=[self.row(room="ZZNEWROOM", row_type="clinic")])
        self.db.commit()
        staged = self.db.query(FaxIngestRow).one()
        self.assertEqual(staged.source_location_id, self.location.id)
        self.assertEqual(staged.row_type, "surgical")  # card is at an OR
        self.assertIsNone(staged.extraction_flags)

    def test_unknown_room_on_unassigned_card_is_flagged(self):
        stage_reviewed_rows(self.db, external_fax_id=171, source_label="Fax 171", rows=[self.row(room="ZZNEWROOM", start_time=time(13, 30))])
        self.db.commit()
        staged = self.db.query(FaxIngestRow).one()
        self.assertIsNone(staged.source_location_id)
        self.assertIsNone(staged.extraction_flags)
        self.assertEqual(self.db.query(FaxRowDecision).one().reason_code, "no_block_for_facility")

    def test_two_blocks_leave_the_hospital_blank(self):
        self._block(self.location, time(7, 0), time(12, 0))
        self._block(self.ap_location, time(7, 0), time(12, 0))
        stage_reviewed_rows(self.db, external_fax_id=174, source_label="Fax 174", rows=[self.row(room="APK S03")])
        self.db.commit()
        staged = self.db.query(FaxIngestRow).one()
        decision = self.db.query(FaxRowDecision).one()
        self.assertIsNone(staged.source_location_id)
        self.assertEqual(decision.reason_code, "block_facility_unclear")

    def test_two_identical_printed_rows_keep_distinct_source_identity(self):
        rows = [self.row(), self.row()]
        result = stage_reviewed_rows(
            self.db, external_fax_id=175, source_label="Fax 175", rows=rows,
        )
        self.db.commit()

        staged = self.db.query(FaxIngestRow).order_by(FaxIngestRow.source_row_number).all()
        self.assertEqual(result["materializedRows"], 2)
        self.assertEqual([row.source_row_number for row in staged], [1, 2])
        self.assertEqual(len({row.normalized_key for row in staged}), 2)


if __name__ == "__main__":
    unittest.main()
