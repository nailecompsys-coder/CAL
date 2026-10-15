"""A day-off link has to name that same surgeon's card."""

import os
import unittest
from datetime import date

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("SECRET_KEY", "test-secret")

from sqlalchemy import create_engine, event, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from app.day_off_card_normalization import sync_day_off_card_links
from app.models import Base, DayOff, DayOffScheduleCard, ScheduleCard, ScheduleCardWeek, Surgeon


def _enable_sqlite_foreign_keys(dbapi_connection, _connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


class DayOffCardSurgeonTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        event.listen(self.engine, "connect", _enable_sqlite_foreign_keys)
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)

    def tearDown(self):
        Base.metadata.drop_all(self.engine)
        self.engine.dispose()

    def _card(self, db, surgeon, day):
        week = ScheduleCardWeek(
            surgeon_id=surgeon.id,
            week_start=date(2026, 10, 19),
            master_revision="test",
        )
        db.add(week)
        db.flush()
        card = ScheduleCard(
            week_id=week.id,
            surgeon_id=surgeon.id,
            date=day,
            session="am",
            baseline_state="na",
            effective_state="na",
        )
        db.add(card)
        db.flush()
        return card

    def test_same_surgeon_link_is_saved(self):
        db = self.Session()
        try:
            surgeon = Surgeon(first_name="Alex", last_name="Smith", email="as@example.com", is_active=True)
            db.add(surgeon)
            db.flush()
            day = date(2026, 10, 19)
            card = self._card(db, surgeon, day)
            off = DayOff(surgeon_id=surgeon.id, start_date=day, end_date=day, status="approved")
            db.add(off)
            db.flush()
            db.add(DayOffScheduleCard(
                day_off_id=off.id,
                schedule_card_id=card.id,
                surgeon_id=surgeon.id,
            ))
            db.commit()
            self.assertEqual(db.query(DayOffScheduleCard).count(), 1)
        finally:
            db.close()

    def test_other_surgeon_card_is_refused(self):
        db = self.Session()
        try:
            owner = Surgeon(first_name="Alex", last_name="Smith", email="as@example.com", is_active=True)
            other = Surgeon(first_name="Chris", last_name="Johnson", email="cj@example.com", is_active=True)
            db.add_all([owner, other])
            db.flush()
            day = date(2026, 10, 19)
            card = self._card(db, other, day)
            off = DayOff(surgeon_id=owner.id, start_date=day, end_date=day, status="approved")
            db.add(off)
            db.flush()
            db.add(DayOffScheduleCard(
                day_off_id=off.id,
                schedule_card_id=card.id,
                surgeon_id=owner.id,
            ))
            with self.assertRaises(IntegrityError):
                db.commit()
        finally:
            db.close()

    def test_sync_links_only_that_surgeon(self):
        db = self.Session()
        try:
            owner = Surgeon(first_name="Alex", last_name="Smith", email="as@example.com", is_active=True)
            other = Surgeon(first_name="Chris", last_name="Johnson", email="cj@example.com", is_active=True)
            db.add_all([owner, other])
            db.flush()
            day = date(2026, 10, 19)
            own_card = self._card(db, owner, day)
            self._card(db, other, day)
            off = DayOff(surgeon_id=owner.id, start_date=day, end_date=day, status="approved", is_full_day=True)
            db.add(off)
            db.flush()
            self.assertEqual(sync_day_off_card_links(db, off), 1)
            link = db.query(DayOffScheduleCard).one()
            self.assertEqual(link.schedule_card_id, own_card.id)
            self.assertEqual(link.surgeon_id, owner.id)
        finally:
            db.close()

    def test_schema_names_both_surgeon_keys(self):
        with self.engine.connect() as conn:
            ddl = conn.execute(text(
                "SELECT sql FROM sqlite_master WHERE name = 'day_off_schedule_cards'"
            )).scalar()
        self.assertIn("fk_day_off_schedule_cards_day_off_surgeon", ddl)
        self.assertIn("fk_day_off_schedule_cards_card_surgeon", ddl)
        self.assertIn("surgeon_id", ddl)
