"""One live day-off request for a surgeon and those dates."""

import os
import unittest
from datetime import date

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("SECRET_KEY", "test-secret")

from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from app.models import Base, DayOff, Surgeon


class DayOffOneRequestTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)

    def tearDown(self):
        Base.metadata.drop_all(self.engine)
        self.engine.dispose()

    def _surgeon(self, db, email):
        surgeon = Surgeon(first_name="Alex", last_name="Smith", email=email, is_active=True)
        db.add(surgeon)
        db.flush()
        return surgeon

    def test_second_live_request_is_refused(self):
        db = self.Session()
        try:
            surgeon = self._surgeon(db, "as@example.com")
            day = date(2026, 12, 8)
            db.add(DayOff(
                surgeon_id=surgeon.id, start_date=day, end_date=day,
                status="approved", reason="Vacation",
            ))
            db.commit()
            db.add(DayOff(
                surgeon_id=surgeon.id, start_date=day, end_date=day,
                status="pending", reason="Day Off",
            ))
            with self.assertRaises(IntegrityError):
                db.commit()
        finally:
            db.close()

    def test_no_call_can_sit_beside_time_off(self):
        db = self.Session()
        try:
            surgeon = self._surgeon(db, "as@example.com")
            day = date(2026, 12, 8)
            db.add_all([
                DayOff(
                    surgeon_id=surgeon.id, start_date=day, end_date=day,
                    status="approved", reason="Partial Day", is_full_day=False,
                ),
                DayOff(
                    surgeon_id=surgeon.id, start_date=day, end_date=day,
                    status="approved", reason="No Call",
                ),
            ])
            db.commit()
            self.assertEqual(db.query(DayOff).count(), 2)
        finally:
            db.close()

    def test_start_after_end_is_refused(self):
        db = self.Session()
        try:
            surgeon = self._surgeon(db, "as@example.com")
            db.add(DayOff(
                surgeon_id=surgeon.id,
                start_date=date(2026, 12, 10),
                end_date=date(2026, 12, 8),
                status="pending",
                reason="Vacation",
            ))
            with self.assertRaises(IntegrityError):
                db.commit()
        finally:
            db.close()

    def test_denied_request_can_be_filed_again(self):
        db = self.Session()
        try:
            surgeon = self._surgeon(db, "as@example.com")
            day = date(2026, 12, 8)
            db.add(DayOff(
                surgeon_id=surgeon.id, start_date=day, end_date=day,
                status="denied", reason="Vacation",
            ))
            db.commit()
            db.add(DayOff(
                surgeon_id=surgeon.id, start_date=day, end_date=day,
                status="pending", reason="Vacation",
            ))
            db.commit()
            self.assertEqual(db.query(DayOff).count(), 2)
        finally:
            db.close()

    def test_schema_names_the_one_request_keys(self):
        with self.engine.connect() as conn:
            names = {
                row[0]
                for row in conn.execute(text(
                    "SELECT name FROM sqlite_master WHERE tbl_name = 'days_off'"
                ))
            }
        self.assertIn("uq_days_off_live_leave", names)
        self.assertIn("uq_days_off_live_no_call", names)
        with self.engine.connect() as conn:
            ddl = conn.execute(text(
                "SELECT sql FROM sqlite_master WHERE name = 'days_off'"
            )).scalar()
        self.assertIn("ck_days_off_start_before_end", ddl)
