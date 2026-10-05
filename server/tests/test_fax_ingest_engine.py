import os
import unittest
from datetime import date, time

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("SECRET_KEY", "test-secret")

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.fax_ingest_engine import ReviewedFaxRow, stage_reviewed_rows
from app.migrate_fax_ingest import create_applicable_view
from app.models import Base, FaxIngestRow, FaxRowDecision, Location, ScheduleCard, ScheduleCardWeek, Surgeon


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

    def test_generic_room_on_na_is_reviewed_not_assigned(self):
        result = stage_reviewed_rows(self.db, external_fax_id=169, source_label="Fax 169", rows=[self.row(start_time=time(13, 30), room="AHMGGENSRG")])
        self.db.commit()
        decision = self.db.query(FaxRowDecision).one()
        self.assertEqual(result["decisions"], {"needs_review": 1})
        self.assertEqual(decision.reason_code, "generic_room_on_na")
        self.assertIsNone(decision.schedule_card.effective_location_id)

    def test_generic_room_on_na_uses_nearest_prior_same_day_location(self):
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
        self.assertEqual([decision.reason_code for decision in decisions[1:]], ["na_context_location", "na_context_location"])
        self.assertEqual({row.source_location_id for row in staged[1:]}, {self.ap_location.id})

    def test_epic_location_override_is_ready_for_existing_card(self):
        result = stage_reviewed_rows(
            self.db,
            external_fax_id=172,
            source_label="Fax 172",
            rows=[self.row(room="APK S03")],
        )
        self.db.commit()
        decision = self.db.query(FaxRowDecision).one()
        self.assertEqual(result["decisions"], {"ready": 1})
        self.assertEqual(decision.reason_code, "epic_override")

    def test_generic_rows_follow_explicit_same_session_epic_location(self):
        result = stage_reviewed_rows(
            self.db,
            external_fax_id=173,
            source_label="Fax 173",
            rows=[
                self.row(start_time=time(13, 10), room="APK S03"),
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


if __name__ == "__main__":
    unittest.main()
