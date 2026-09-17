import os
import unittest
from datetime import date, time

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("SECRET_KEY", "test-secret")

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.fax_ingest_engine import ReviewedFaxRow, stage_reviewed_rows
from app.models import Base, FaxIngestRow, FaxRowDecision, Location, ScheduleCard, ScheduleCardWeek, Surgeon


class FaxIngestEngineTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)
        self.db = self.Session()
        self.surgeon = Surgeon(first_name="Jorge", last_name="Florin", is_active=True, staff_type="physician")
        self.location = Location(name="Minneola OR", abbreviation="MN-OR", location_type="hospital", is_active=True)
        self.db.add_all([self.surgeon, self.location])
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
