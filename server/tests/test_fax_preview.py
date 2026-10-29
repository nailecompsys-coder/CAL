import os
import unittest
from datetime import date, time

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("SECRET_KEY", "test-secret")

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.fax_ingest_engine import ReviewedFaxRow
from app.fax_preview import preview_reviewed_rows
from app.models import (
    Base,
    FaxDocument,
    FaxIngestRow,
    Location,
    ORBlockAssignment,
    ORBlockInstance,
    ScheduleCard,
    ScheduleCardActivity,
    ScheduleCardWeek,
    Surgeon,
)

MONDAY = date(2099, 9, 21)
TUESDAY = date(2099, 9, 22)
WEDNESDAY = date(2099, 9, 23)
SATURDAY = date(2099, 9, 26)


def _row(day, clock, patient, room="WGD S07", row_type="surgical"):
    return ReviewedFaxRow(
        page=1, surgeon_initials="JF", surgeon_name="Jorge Florin", case_date=day,
        start_time=clock, row_type=row_type, room=room, patient_name=patient, procedure="Lap chole",
    )


class FaxPreviewTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.db = sessionmaker(bind=self.engine)()
        surgeon = Surgeon(first_name="Jorge", last_name="Florin", email="jf@example.com", is_active=True)
        wg_or = Location(name="Winter Garden OR", abbreviation="WG-OR", location_type="hospital", is_active=True)
        al_or = Location(name="Altamonte OR", abbreviation="AL-OR", location_type="hospital", is_active=True)
        self.surgeon = surgeon
        self.wg_or = wg_or
        self.db.add_all([surgeon, wg_or, al_or])
        self.db.flush()
        week = ScheduleCardWeek(surgeon_id=surgeon.id, week_start=MONDAY, master_revision="test")
        self.db.add(week)
        self.db.flush()

        def card(day, session, state, location=None):
            return ScheduleCard(
                week_id=week.id, surgeon_id=surgeon.id, date=day, session=session,
                baseline_state=state, effective_state=state,
                baseline_location_id=location, effective_location_id=location, source="master",
            )

        mon_am = card(MONDAY, "am", "assigned", wg_or.id)
        moved = card(WEDNESDAY, "am", "assigned", al_or.id)
        moved.effective_location_id = wg_or.id
        self.db.add_all([mon_am, card(MONDAY, "pm", "na"), card(TUESDAY, "am", "off"), card(TUESDAY, "pm", "assigned", al_or.id), moved])
        self.db.flush()
        for patient, clock in (("Already, There", time(8, 0)), ("Not, OnFax", time(10, 0))):
            self.db.add(ScheduleCardActivity(
                schedule_card_id=mon_am.id, surgeon_id=surgeon.id, location_id=wg_or.id,
                activity_date=MONDAY, session="am", activity_type="surgical", start_time=clock,
                patient_name=patient, procedure="Lap chole", source_system="surgical_case",
                source_record_key=patient, identity_key=patient,
            ))
        self.db.commit()
        self._block(wg_or, MONDAY, time(12, 0), time(17, 0))
        self._block(wg_or, TUESDAY, time(12, 0), time(17, 0))
        self._block(wg_or, WEDNESDAY, time(7, 0), time(12, 0))

    def _block(self, location, day, start, end):
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

    def test_rows_are_labelled_against_the_live_schedule_and_nothing_is_saved(self):
        result = preview_reviewed_rows(self.db, external_fax_id=300, source_label="test", rows=[
            _row(MONDAY, time(8, 0), "Already, There"),
            _row(MONDAY, time(13, 0), "Fills, NA"),
            _row(TUESDAY, time(8, 0), "On, Off"),
            _row(TUESDAY, time(13, 0), "Wrong, Facility"),
            _row(SATURDAY, time(8, 0), "Weekend, Misread"),
            _row(WEDNESDAY, time(8, 0), "Agrees, WithCard"),
        ])

        labels = {row["patient_name"]: (row["label"], row["reason_code"]) for row in result["rows"]}
        self.assertEqual(labels["Already, There"][0], "match")
        self.assertEqual(labels["Fills, NA"][0], "addition")
        self.assertEqual(labels["On, Off"], ("fail", "no_block_for_facility"))
        self.assertEqual(labels["Wrong, Facility"], ("fail", "location_conflict"))
        self.assertEqual(labels["Weekend, Misread"], ("fail", "weekend_schedule"))
        self.assertEqual(labels["Agrees, WithCard"], ("addition", "existing_card"))
        self.assertEqual([row["patient_name"] for row in result["calOnly"]], ["Not, OnFax"])
        self.assertEqual(self.db.query(FaxIngestRow).count(), 0)
        self.assertEqual(self.db.query(FaxDocument).count(), 0)


if __name__ == "__main__":
    unittest.main()
