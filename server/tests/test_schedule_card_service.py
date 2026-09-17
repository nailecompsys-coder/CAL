import os
import unittest
from datetime import date

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("SECRET_KEY", "test-secret")

from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from app.models import Base, Location, ScheduleCard, ScheduleCardWeek, Surgeon, SurgeonLocationSchedule
from app.schedule_card_service import apply_master_schedule_to_cards, materialize_master_schedule_cards


class ScheduleCardServiceTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)

    def tearDown(self):
        Base.metadata.drop_all(self.engine)
        self.engine.dispose()

    def test_materializes_ten_per_surgeon_week_and_preserves_identity(self):
        db = self.Session()
        try:
            surgeon = Surgeon(first_name="Alex", last_name="Smith", email="as@example.com", is_active=True, staff_type="physician")
            location = Location(name="Minneola OR", abbreviation="MN-OR", location_type="hospital", is_active=True)
            db.add_all([surgeon, location])
            db.commit()
            db.add(SurgeonLocationSchedule(
                surgeon_id=surgeon.id, day_of_week=1, session="pm", location_id=location.id,
                assignment_type="na", week_pattern="all",
            ))
            db.commit()

            result = materialize_master_schedule_cards(db, start=date(2026, 9, 14), end=date(2026, 9, 18))
            db.commit()
            self.assertEqual(result["cardsCreated"], 10)
            self.assertEqual(db.query(ScheduleCardWeek).count(), 1)
            cards = db.query(ScheduleCard).filter(ScheduleCard.surgeon_id == surgeon.id).all()
            self.assertEqual(len(cards), 10)
            target = next(row for row in cards if row.date == date(2026, 9, 15) and row.session == "pm")
            self.assertEqual(target.baseline_state, "na")
            self.assertEqual(target.baseline_location_id, location.id)
            target_id = target.id

            again = materialize_master_schedule_cards(db, start=date(2026, 9, 14), end=date(2026, 9, 18))
            db.commit()
            self.assertEqual(again["cardsCreated"], 0)
            self.assertEqual(db.get(ScheduleCard, target_id).id, target_id)
        finally:
            db.close()

    def test_database_unique_key_rejects_a_third_card_for_a_session(self):
        db = self.Session()
        try:
            surgeon = Surgeon(first_name="Alex", last_name="Smith", email="as@example.com", is_active=True, staff_type="physician")
            db.add(surgeon)
            db.commit()
            materialize_master_schedule_cards(db, start=date(2026, 9, 14), end=date(2026, 9, 18))
            db.commit()
            week = db.query(ScheduleCardWeek).one()
            db.add(ScheduleCard(
                week_id=week.id, surgeon_id=surgeon.id, date=date(2026, 9, 14), session="am",
                baseline_state="na", effective_state="na", source="test",
            ))
            with self.assertRaises(IntegrityError):
                db.commit()
            db.rollback()
        finally:
            db.close()

    def test_assigned_state_requires_a_location(self):
        db = self.Session()
        try:
            surgeon = Surgeon(first_name="Alex", last_name="Smith", email="as@example.com", is_active=True, staff_type="physician")
            week = ScheduleCardWeek(surgeon=surgeon, week_start=date(2026, 9, 14))
            db.add(week)
            db.flush()
            db.add(ScheduleCard(
                week_id=week.id, surgeon_id=surgeon.id, date=date(2026, 9, 14), session="am",
                baseline_state="assigned", effective_state="assigned", source="test",
            ))
            with self.assertRaises(IntegrityError):
                db.commit()
            db.rollback()
        finally:
            db.close()

    def test_master_apply_updates_existing_cards_without_creating_any(self):
        db = self.Session()
        try:
            surgeon = Surgeon(first_name="Alex", last_name="Smith", email="as@example.com", is_active=True, staff_type="physician")
            location = Location(name="Minneola OR", abbreviation="MN-OR", location_type="hospital", is_active=True)
            db.add_all([surgeon, location])
            db.commit()
            materialize_master_schedule_cards(db, start=date(2026, 9, 14), end=date(2026, 9, 18))
            db.commit()
            target = db.query(ScheduleCard).filter_by(
                surgeon_id=surgeon.id, date=date(2026, 9, 15), session="pm"
            ).one()
            target_id = target.id
            self.assertEqual(target.baseline_state, "na")

            db.add(SurgeonLocationSchedule(
                surgeon_id=surgeon.id, day_of_week=1, session="pm", location_id=location.id,
                assignment_type="assigned", week_pattern="all",
            ))
            db.commit()
            result = apply_master_schedule_to_cards(db, start=date(2026, 9, 14), end=date(2026, 9, 18))
            db.commit()
            updated = db.get(ScheduleCard, target_id)
            self.assertEqual(result["cardsApplied"], 10)
            self.assertGreaterEqual(result["cardsChanged"], 1)
            self.assertEqual(db.query(ScheduleCard).count(), 10)
            self.assertEqual(updated.baseline_state, "assigned")
            self.assertEqual(updated.baseline_location_id, location.id)
            self.assertEqual(updated.id, target_id)
        finally:
            db.close()

    def test_master_apply_refuses_to_recreate_missing_card(self):
        db = self.Session()
        try:
            surgeon = Surgeon(first_name="Alex", last_name="Smith", email="as@example.com", is_active=True, staff_type="physician")
            db.add(surgeon)
            db.commit()
            materialize_master_schedule_cards(db, start=date(2026, 9, 14), end=date(2026, 9, 18))
            db.commit()
            db.query(ScheduleCard).filter_by(surgeon_id=surgeon.id, date=date(2026, 9, 15), session="pm").delete()
            db.commit()
            with self.assertRaisesRegex(ValueError, "Missing permanent schedule card"):
                apply_master_schedule_to_cards(db, start=date(2026, 9, 14), end=date(2026, 9, 18))
            self.assertEqual(db.query(ScheduleCard).count(), 9)
        finally:
            db.close()


if __name__ == "__main__":
    unittest.main()
