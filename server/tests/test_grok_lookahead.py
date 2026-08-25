import os
import unittest
from datetime import date, time, timedelta

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("SECRET_KEY", "test-secret")

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.grok_lookahead_service import build_grok_lookahead
from app.models import (
    Base,
    CallCoverage,
    CallGroup,
    CallRotation,
    DayOff,
    Location,
    Surgeon,
    SurgicalCase,
)


class GrokLookaheadTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(bind=self.engine)
        self.Session = sessionmaker(bind=self.engine)

    def tearDown(self):
        Base.metadata.drop_all(bind=self.engine)
        self.engine.dispose()

    def _seed_docs(self, db):
        covering = Surgeon(
            first_name="Jason", last_name="Boardman",
            email="jb@example.com", is_active=True, staff_type="physician",
        )
        original = Surgeon(
            first_name="Alex", last_name="Schroeder",
            email="as@example.com", is_active=True, staff_type="physician",
        )
        group = CallGroup(name="Winter Garden", sort_order=1)
        db.add_all([covering, original, group])
        db.commit()
        return covering, original, group

    def test_cover_while_off_is_flagged(self):
        db = self.Session()
        try:
            covering, original, group = self._seed_docs(db)
            day = date.today() + timedelta(days=5)
            rotation = CallRotation(
                surgeon_id=original.id, date=day, call_group_id=group.id, rotation_type="primary",
            )
            db.add(rotation)
            db.flush()
            db.add(CallCoverage(
                call_rotation_id=rotation.id,
                original_surgeon_id=original.id,
                covering_surgeon_id=covering.id,
                requested_by_surgeon_id=original.id,
                status="active",
            ))
            db.add(DayOff(
                surgeon_id=covering.id,
                start_date=day,
                end_date=day,
                status="approved",
                reason="Day Off",
            ))
            db.commit()

            payload = build_grok_lookahead(db, today=date.today())
            kinds = [row["kind"] for row in payload["issues"]]
            self.assertIn("cover_while_off", kinds)
            self.assertIn("JB", payload["issues"][0]["message"])
            self.assertIn("AS", payload["issues"][0]["message"])
            self.assertNotIn("PTO", payload["briefing"])
            self.assertIn("doctors involved", payload["briefing"])
            self.assertTrue(payload["issues"][0]["href"].startswith("/admin/call-schedule"))
        finally:
            db.close()

    def test_on_call_while_off_without_cover(self):
        db = self.Session()
        try:
            _, original, group = self._seed_docs(db)
            day = date.today() + timedelta(days=3)
            db.add(CallRotation(
                surgeon_id=original.id, date=day, call_group_id=group.id, rotation_type="primary",
            ))
            db.add(DayOff(
                surgeon_id=original.id,
                start_date=day,
                end_date=day,
                status="approved",
                reason="Day Off",
            ))
            db.commit()

            payload = build_grok_lookahead(db, today=date.today())
            self.assertEqual(payload["issues"][0]["kind"], "on_call_while_off")
            self.assertIn("no cover assigned", payload["issues"][0]["message"])
        finally:
            db.close()

    def test_clear_window_has_empty_briefing(self):
        db = self.Session()
        try:
            self._seed_docs(db)
            payload = build_grok_lookahead(db, today=date.today())
            self.assertEqual(payload["issueCount"], 0)
            self.assertIn("look clear", payload["briefing"])
            self.assertEqual(payload["voice"], "cal")
        finally:
            db.close()

    def test_off_with_or_work_is_flagged(self):
        db = self.Session()
        try:
            covering, _, _ = self._seed_docs(db)
            day = date.today() + timedelta(days=4)
            loc = Location(name="WG OR", abbreviation="WG", location_type="hospital", is_active=True)
            db.add(loc)
            db.flush()
            db.add(DayOff(
                surgeon_id=covering.id,
                start_date=day,
                end_date=day,
                status="approved",
                reason="Day Off",
            ))
            db.add(SurgicalCase(
                surgeon_id=covering.id,
                date=day,
                start_time=time(8, 0),
                patient_name="TEST, PATIENT",
                procedure="ORIF",
                location_id=loc.id,
                status="scheduled",
            ))
            db.commit()

            payload = build_grok_lookahead(db, today=date.today())
            self.assertEqual(payload["issues"][0]["kind"], "off_with_work")
            self.assertIn("/admin/clinic-schedule", payload["issues"][0]["href"])
        finally:
            db.close()
