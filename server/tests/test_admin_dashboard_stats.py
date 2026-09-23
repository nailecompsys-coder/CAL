import os
import unittest
from datetime import date, time

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.admin_dashboard_stats_service import (
    clinic_visits_today_count,
    dashboard_today_volume_stats,
    surgical_cases_today_count,
)
from app.models import Base, Location, ScheduleCard, ScheduleCardActivity, Surgeon
from app.schedule_card_service import materialize_master_schedule_cards


class AdminDashboardStatsTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(bind=self.engine)
        self.Session = sessionmaker(bind=self.engine)
        self.day = date(2026, 7, 23)

    def tearDown(self):
        Base.metadata.drop_all(bind=self.engine)
        self.engine.dispose()

    def _surgeon(self, db, first="Chris", last="Johnson"):
        row = Surgeon(
            first_name=first,
            last_name=last,
            email=f"{first.lower()}.{last.lower()}@example.com",
            is_active=True,
            staff_type="physician",
        )
        db.add(row)
        db.flush()
        return row

    def test_surgical_cases_today_excludes_cancelled_and_other_days(self):
        db = self.Session()
        try:
            surgeon = self._surgeon(db)
            loc = Location(name="WG OR", abbreviation="WG-OR", location_type="hospital", is_active=True)
            db.add(loc)
            db.flush()
            db.commit()
            materialize_master_schedule_cards(db, start=self.day, end=date(2026, 7, 24))
            cards = {
                row.date: row for row in db.query(ScheduleCard).filter_by(surgeon_id=surgeon.id, session="am").all()
            }
            db.add_all([
                ScheduleCardActivity(
                    schedule_card_id=cards[self.day].id, surgeon_id=surgeon.id, location_id=loc.id,
                    activity_date=self.day, session="am", activity_type="surgical", start_time=time(8),
                    patient_name="A, Patient", source_system="test", source_record_key="a",
                    identity_key="apatient|08:00:00|surgical", is_active=True,
                ),
                ScheduleCardActivity(
                    schedule_card_id=cards[self.day].id, surgeon_id=surgeon.id, location_id=loc.id,
                    activity_date=self.day, session="am", activity_type="surgical", start_time=time(9),
                    patient_name="B, Patient", source_system="test", source_record_key="b",
                    identity_key="bpatient|09:00:00|surgical", is_active=False,
                ),
                ScheduleCardActivity(
                    schedule_card_id=cards[date(2026, 7, 24)].id, surgeon_id=surgeon.id, location_id=loc.id,
                    activity_date=date(2026, 7, 24), session="am", activity_type="surgical", start_time=time(8),
                    patient_name="C, Patient", source_system="test", source_record_key="c",
                    identity_key="cpatient|08:00:00|surgical", is_active=True,
                ),
            ])
            db.commit()
            self.assertEqual(surgical_cases_today_count(db, self.day), 1)
        finally:
            db.close()

    def test_clinic_visits_count_distinct_normalized_rows(self):
        db = self.Session()
        try:
            surgeon = self._surgeon(db)
            clinic = Location(name="WG Clinic", abbreviation="WG", location_type="clinic", is_active=True)
            db.add(clinic)
            db.flush()
            db.commit()
            materialize_master_schedule_cards(db, start=self.day, end=self.day)
            card = db.query(ScheduleCard).filter_by(
                surgeon_id=surgeon.id, date=self.day, session="am"
            ).one()
            rows = []
            for index, patient in enumerate(("Nieves, Rosa", "Pinder, Joe", "Third, Patient", "Fourth, Patient")):
                rows.append(ScheduleCardActivity(
                    schedule_card_id=card.id, surgeon_id=surgeon.id, location_id=clinic.id,
                    activity_date=self.day, session="am", activity_type="clinic",
                    start_time=time(8, index * 10), patient_name=patient,
                    source_system="test", source_record_key=f"clinic-{index}",
                    identity_key=f"patient{index}|08:{index * 10:02d}:00|clinic",
                ))
            db.add_all(rows)
            db.commit()
            self.assertEqual(clinic_visits_today_count(db, self.day), 4)
            stats = dashboard_today_volume_stats(db, self.day)
            self.assertEqual(stats["clinic_visits_today"], 4)
            self.assertEqual(stats["surgical_cases_today"], 0)
        finally:
            db.close()


if __name__ == "__main__":
    unittest.main()
