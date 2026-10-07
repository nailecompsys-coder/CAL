import os
import unittest
from datetime import date, time

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("SECRET_KEY", "test-secret")

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models import (
    Base, CallDailyAssignment, CallGroup, CallRotation, DayOff, Location, ScheduleCard, ScheduleCardWeek, Surgeon,
)
from app.native_whos_where import whos_where

MONDAY = date(2026, 10, 12)


class NativeWhosWhereTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(bind=self.engine)
        self.db = sessionmaker(bind=self.engine)()
        self.wg = CallGroup(name="Winter Garden / Apopka / Minneola Hospital", sort_order=1)
        self.al = CallGroup(name="Altamonte Hospital", sort_order=2)
        self.db.add_all([self.wg, self.al])
        self.db.flush()
        self.wg_or = Location(name="Winter Garden OR", abbreviation="WG-OR", location_type="hospital",
                              color="#E48EA6", block_group_id=self.wg.id)
        self.al_ov = Location(name="Altamonte Clinic", abbreviation="AL-OV", location_type="clinic",
                              color="#D8F6F0", block_group_id=self.al.id)
        self.doc = Surgeon(first_name="Chris", last_name="Johnson", sort_order=2, is_active=True)
        self.other = Surgeon(first_name="Alex", last_name="Schroeder", sort_order=1, is_active=True)
        self.pa = Surgeon(first_name="Amy", last_name="Diehl", staff_type="staff", is_active=True)
        self.db.add_all([self.wg_or, self.al_ov, self.doc, self.other, self.pa])
        self.db.flush()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def _card(self, surgeon, session, location=None, state="assigned"):
        week = self.db.query(ScheduleCardWeek).filter_by(surgeon_id=surgeon.id).one_or_none()
        if week is None:
            week = ScheduleCardWeek(surgeon_id=surgeon.id, week_start=MONDAY)
            self.db.add(week)
            self.db.flush()
        self.db.add(ScheduleCard(
            week_id=week.id, surgeon_id=surgeon.id, date=MONDAY, session=session,
            baseline_state=state, effective_state=state,
            baseline_location_id=location.id if location else None,
            effective_location_id=location.id if location else None,
        ))

    def test_places_each_half_day_in_its_location_group(self):
        self._card(self.doc, "am", self.wg_or)
        self._card(self.doc, "pm", self.al_ov)
        self._card(self.pa, "am", state="na")
        self._card(self.pa, "pm", state="na")
        self.db.commit()

        rows = whos_where(self.db, MONDAY)
        doc = {r["session"]: r for r in rows if r["surgeonId"] == self.doc.id}
        self.assertEqual((doc["am"]["location"], doc["am"]["group"]), ("WG-OR", self.wg.name))
        self.assertEqual((doc["pm"]["location"], doc["pm"]["group"]), ("AL-OV", self.al.name))
        pa_am = next(r for r in rows if r["surgeonId"] == self.pa.id and r["session"] == "am")
        self.assertEqual((pa_am["state"], pa_am["groupId"], pa_am["staffType"]), ("na", None, "staff"))
        self.assertEqual([r["session"] for r in rows], ["am", "am", "pm", "pm"])
        self.assertEqual(rows[0]["surgeonId"], self.doc.id)

    def test_partial_leave_no_call_and_call_are_marked(self):
        self._card(self.other, "am", self.wg_or)
        self._card(self.other, "pm", self.wg_or)
        self.db.add_all([
            DayOff(surgeon_id=self.other.id, start_date=MONDAY, end_date=MONDAY, reason="Partial Day",
                   status="approved", is_full_day=False, start_time=time(7), end_time=time(12)),
            DayOff(surgeon_id=self.other.id, start_date=MONDAY, end_date=MONDAY, reason="No Call",
                   status="approved", is_full_day=True),
        ])
        rotation = CallRotation(call_group_id=self.wg.id, surgeon_id=self.doc.id, date=MONDAY, rotation_type="primary")
        self.db.add(rotation)
        self.db.flush()
        self.db.add(CallDailyAssignment(date=MONDAY, location_id=self.wg_or.id, surgeon_id=self.doc.id,
                                        call_group_id=self.wg.id, call_rotation_id=rotation.id))
        self.db.commit()

        rows = whos_where(self.db, MONDAY)
        other = {r["session"]: r for r in rows if r["surgeonId"] == self.other.id}
        self.assertTrue(other["am"]["onLeave"])
        self.assertFalse(other["pm"]["onLeave"])
        self.assertTrue(other["pm"]["noCall"])
        call = [r for r in rows if r["session"] == "call"]
        self.assertEqual([(r["surgeonId"], r["groupId"]) for r in call], [(self.doc.id, self.wg.id)])

    def test_rows_carry_no_patient_fields(self):
        self._card(self.doc, "am", self.wg_or)
        self.db.commit()
        keys = set(whos_where(self.db, MONDAY)[0])
        self.assertFalse(keys & {"patient", "patientName", "procedure", "caseCount", "room"})


if __name__ == "__main__":
    unittest.main()
