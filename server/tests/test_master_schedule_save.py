import os
import unittest
from datetime import date

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("SECRET_KEY", "test-secret")

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.admin_schedule_template_clinic_service import add_master_schedule_location, save_template_cell_value
from app.models import Base, Location, ScheduleCard, Surgeon
from app.schedule_card_service import apply_master_schedule_to_cards, materialize_master_schedule_cards


class MasterScheduleSaveTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)

    def tearDown(self):
        Base.metadata.drop_all(self.engine)
        self.engine.dispose()

    def test_master_save_updates_existing_cards_without_creating_any(self):
        db = self.Session()
        try:
            surgeon = Surgeon(first_name="Alex", last_name="Smith", email="as@example.com", is_active=True, staff_type="physician")
            location = Location(name="Minneola OR", abbreviation="MN-OR", location_type="hospital", is_active=True)
            db.add_all([surgeon, location])
            db.commit()
            materialize_master_schedule_cards(db, start=date(2026, 9, 14), end=date(2026, 9, 18))
            db.commit()
            original_count = db.query(ScheduleCard).count()
            save_template_cell_value(db, surgeon.id, 0, "am", location.id, "assigned", commit=False)
            apply_master_schedule_to_cards(db, start=date(2026, 9, 14), end=date(2026, 9, 18), surgeon_ids=[surgeon.id])
            db.commit()
            card = db.query(ScheduleCard).filter_by(surgeon_id=surgeon.id, date=date(2026, 9, 14), session="am").one()
            self.assertEqual(card.effective_location_id, location.id)
            self.assertEqual(db.query(ScheduleCard).count(), original_count)
        finally:
            db.close()

    def test_blank_and_float_normalize_to_na(self):
        db = self.Session()
        try:
            surgeon = Surgeon(first_name="Alex", last_name="Smith", email="as@example.com", is_active=True, staff_type="physician")
            db.add(surgeon)
            db.commit()
            save_template_cell_value(db, surgeon.id, 0, "am", None, "blank")
            db.commit()
            row = surgeon.location_schedules[0]
            self.assertEqual(row.assignment_type, "na")
            self.assertIsNone(row.location_id)
        finally:
            db.close()

    def test_new_location_does_not_create_or_change_schedule_cards(self):
        db = self.Session()
        try:
            surgeon = Surgeon(first_name="Alex", last_name="Smith", email="as@example.com", is_active=True, staff_type="physician")
            db.add(surgeon)
            db.commit()
            materialize_master_schedule_cards(db, start=date(2026, 9, 14), end=date(2026, 9, 18))
            db.commit()
            before = db.query(ScheduleCard).count()
            location = add_master_schedule_location(db, name="New Hospital", abbreviation="NH-OR", location_type="hospital")
            db.commit()
            self.assertEqual(location.abbreviation, "NH-OR")
            self.assertEqual(db.query(ScheduleCard).count(), before)
        finally:
            db.close()


if __name__ == "__main__":
    unittest.main()
