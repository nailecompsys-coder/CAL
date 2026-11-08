"""The database refuses a repeated meeting person, a repeated Block OR room, and a mismatched card."""

import os
import unittest
from datetime import date, time

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("SECRET_KEY", "test-secret")

from sqlalchemy import create_engine, event, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from app.models import (
    Base,
    Location,
    Meeting,
    MeetingAttendee,
    ORBlockInstance,
    ScheduleCard,
    ScheduleCardWeek,
    Surgeon,
)


def _engine():
    engine = create_engine("sqlite:///:memory:")

    @event.listens_for(engine, "connect")
    def _foreign_keys(dbapi_connection, _record):
        dbapi_connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    return engine


class ScheduleLockTest(unittest.TestCase):
    def setUp(self):
        self.engine = _engine()
        self.db = sessionmaker(bind=self.engine)()
        self.surgeon = Surgeon(first_name="Chris", last_name="Johnson", is_active=True)
        self.other = Surgeon(first_name="Alex", last_name="Smith", is_active=True)
        self.hospital = Location(name="Altamonte", abbreviation="AL", location_type="hospital", is_active=True)
        self.db.add_all([self.surgeon, self.other, self.hospital])
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def test_meeting_keeps_one_row_per_person(self):
        meeting = Meeting(title="Staff", date=date(2026, 10, 20))
        self.db.add(meeting)
        self.db.flush()
        self.db.add(MeetingAttendee(meeting_id=meeting.id, surgeon_id=self.surgeon.id))
        self.db.commit()
        self.db.add(MeetingAttendee(meeting_id=meeting.id, surgeon_id=self.surgeon.id))
        with self.assertRaises(IntegrityError):
            self.db.commit()

    def test_blank_block_rooms_collide(self):
        day = date(2026, 10, 20)
        self.db.add(ORBlockInstance(
            location_id=self.hospital.id,
            date=day,
            session="am",
            start_time=time(7, 0),
            end_time=time(12, 0),
        ))
        self.db.commit()
        self.db.add(ORBlockInstance(
            location_id=self.hospital.id,
            date=day,
            session="am",
            start_time=time(8, 0),
            end_time=time(11, 0),
            room_text="",
        ))
        with self.assertRaises(IntegrityError):
            self.db.commit()

    def test_a_different_room_is_a_second_block(self):
        day = date(2026, 10, 20)
        self.db.add_all([
            ORBlockInstance(
                location_id=self.hospital.id, date=day, session="am",
                start_time=time(7, 0), end_time=time(12, 0), room_text="S03",
            ),
            ORBlockInstance(
                location_id=self.hospital.id, date=day, session="am",
                start_time=time(7, 0), end_time=time(12, 0), room_text="S08",
            ),
        ])
        self.db.commit()
        self.assertEqual(self.db.query(ORBlockInstance).count(), 2)

    def test_card_surgeon_must_match_the_week(self):
        week = ScheduleCardWeek(surgeon_id=self.surgeon.id, week_start=date(2026, 10, 19))
        self.db.add(week)
        self.db.flush()
        self.db.add(ScheduleCard(
            week_id=week.id,
            surgeon_id=self.other.id,
            date=date(2026, 10, 20),
            session="am",
            baseline_state="na",
            effective_state="na",
        ))
        with self.assertRaises(IntegrityError):
            self.db.commit()

    def test_room_index_treats_a_missing_room_as_blank(self):
        rows = self.db.execute(text(
            "SELECT sql FROM sqlite_master WHERE name = 'uq_or_block_instances_location_date_session_room'"
        )).all()
        self.assertTrue(rows)
        sql = (rows[0][0] or "").lower()
        self.assertIn("coalesce", sql)
        self.assertIn("room_text", sql)
