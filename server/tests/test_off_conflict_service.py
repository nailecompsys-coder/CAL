import os
import unittest
from datetime import date, time, timedelta

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("SECRET_KEY", "test-secret")

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.day_off_card_normalization import backfill_day_off_card_links
from app.migrate_fax_ingest import create_applicable_view
from app.clinic_schedule_card_guard import present_card, set_card_place
from app.models import Base, DayOff, Location, ScheduleCard, ScheduleCardActivity, Surgeon
from app.off_conflict_service import (
    detect_off_conflicts,
    should_show_as_off,
    build_clinic_off_display,
    day_off_status_map,
    schedule_matches_off_session,
)
from app.schedule_activity_normalization import backfill_normalized_schedule_activity
from app.schedule_card_service import materialize_master_schedule_cards


class OffConflictServiceTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(bind=self.engine)
        with self.engine.begin() as conn:
            create_applicable_view(conn)
        self.Session = sessionmaker(bind=self.engine)

    def tearDown(self):
        Base.metadata.drop_all(bind=self.engine)
        self.engine.dispose()

    def _surgeon(self, db, first, last):
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

    def _soon(self, days_ahead):
        day = date.today() + timedelta(days=days_ahead)
        while day.weekday() >= 5:
            day += timedelta(days=1)
        return day

    def _normalize(self, db, day):
        materialize_master_schedule_cards(db, start=day, end=day)
        backfill_day_off_card_links(db)
        backfill_normalized_schedule_activity(db)

    def test_empty_clinic_on_off_shows_as_off_no_conflict(self):
        db = self.Session()
        try:
            chris = self._surgeon(db, "Chris", "Johnson")
            clinic = Location(name="WG Clinic", abbreviation="WG", location_type="clinic", is_active=True)
            db.add(clinic)
            db.flush()
            day = self._soon(1)
            db.add(DayOff(
                surgeon_id=chris.id,
                start_date=day,
                end_date=day,
                status="approved",
                reason="Vacation",
            ))
            db.commit()
            self._normalize(db, day)
            cards = db.query(ScheduleCard).filter_by(surgeon_id=chris.id, date=day).all()
            for card in cards:
                set_card_place(card, clinic.id, "assigned")
            db.commit()

            display = build_clinic_off_display(
                db, day, day,
                sched_map={chris.id: {day: [present_card(card) for card in cards]}},
                surgical_map={},
            )
            self.assertEqual(len(display["off_conflicts"]), 0)
            self.assertTrue(should_show_as_off(chris.id, day, display["off_map"], display["workloads"]))
            self.assertTrue(display["show_off_schedule_ids"])
            self.assertFalse(display["hide_empty_or_blocks"])
        finally:
            db.close()

    def test_partial_day_off_only_overlays_matching_session(self):
        db = self.Session()
        try:
            chris = self._surgeon(db, "Chris", "Johnson")
            clinic = Location(name="Clermont Office", abbreviation="CL-OV", location_type="clinic", is_active=True)
            hospital = Location(name="Minneola OR", abbreviation="MN-OR", location_type="hospital", is_active=True)
            db.add_all([clinic, hospital])
            db.flush()
            day = self._soon(1)
            db.add(DayOff(
                surgeon_id=chris.id,
                start_date=day,
                end_date=day,
                status="approved",
                reason="AM appointment",
                is_full_day=False,
                start_time=time(7, 0),
                end_time=time(12, 0),
            ))
            db.commit()
            self._normalize(db, day)
            am = db.query(ScheduleCard).filter_by(surgeon_id=chris.id, date=day, session="am").one()
            pm = db.query(ScheduleCard).filter_by(surgeon_id=chris.id, date=day, session="pm").one()
            set_card_place(am, hospital.id, "assigned")
            set_card_place(pm, clinic.id, "assigned")
            db.commit()
            schedules = [present_card(am), present_card(pm)]
            display = build_clinic_off_display(
                db, day, day,
                sched_map={chris.id: {day: schedules}},
                surgical_map={},
            )
            off_info = display["off_map"][(chris.id, day)]
            self.assertEqual(off_info["sessions"], {"am"})
            self.assertTrue(schedule_matches_off_session(am, off_info))
            self.assertFalse(schedule_matches_off_session(pm, off_info))
            self.assertIn(am.id, display["show_off_schedule_ids"])
            self.assertNotIn(pm.id, display["show_off_schedule_ids"])
        finally:
            db.close()

    def test_pending_off_with_surgical_case_is_conflict(self):
        db = self.Session()
        try:
            chris = self._surgeon(db, "Chris", "Johnson")
            hospital = Location(name="WG OR", abbreviation="WG-OR", location_type="hospital", is_active=True)
            db.add(hospital)
            db.flush()
            day = self._soon(2)
            db.add(DayOff(
                surgeon_id=chris.id,
                start_date=day,
                end_date=day,
                status="pending",
                reason="Personal",
            ))
            db.commit()
            self._normalize(db, day)
            am = db.query(ScheduleCard).filter_by(
                surgeon_id=chris.id, date=day, session="am",
            ).one()
            db.add(ScheduleCardActivity(
                schedule_card_id=am.id,
                surgeon_id=chris.id,
                location_id=hospital.id,
                activity_date=day,
                session="am",
                activity_type="surgical",
                start_time=time(8, 0),
                end_time=time(9, 0),
                patient_name="Test Patient",
                procedure="Lap chole",
                source_system="fax",
                source_record_key="pending-off-case",
                identity_key="testpatient|08:00:00|surgical",
            ))
            db.commit()

            conflicts = detect_off_conflicts(db, day, day)
            self.assertEqual(len(conflicts), 1)
            self.assertEqual(conflicts[0].day_off_status, "pending")
            self.assertEqual(conflicts[0].case_count, 1)
            self.assertIn("surgical case", conflicts[0].message)
        finally:
            db.close()

    def test_fax_patients_on_approved_off_conflict(self):
        db = self.Session()
        try:
            chris = self._surgeon(db, "Chris", "Johnson")
            clinic = Location(name="Clermont Office", abbreviation="CL", location_type="clinic", is_active=True)
            db.add(clinic)
            db.flush()
            day = self._soon(3)
            db.add(DayOff(
                surgeon_id=chris.id,
                start_date=day,
                end_date=day,
                status="approved",
            ))
            db.commit()
            self._normalize(db, day)
            pm_card = db.query(ScheduleCard).filter_by(
                surgeon_id=chris.id, date=day, session="pm"
            ).one()
            db.add_all([
                ScheduleCardActivity(
                    schedule_card_id=pm_card.id, surgeon_id=chris.id, location_id=clinic.id,
                    activity_date=day, session="pm", activity_type="clinic", start_time=time(13, 0),
                    patient_name="Smith, Jane", source_system="fax_clinic", source_record_key="fax-1",
                    identity_key="smithjane|13:00:00|clinic",
                ),
                ScheduleCardActivity(
                    schedule_card_id=pm_card.id, surgeon_id=chris.id, location_id=clinic.id,
                    activity_date=day, session="pm", activity_type="clinic", start_time=time(13, 15),
                    patient_name="Doe, John", source_system="fax_clinic", source_record_key="fax-2",
                    identity_key="doejohn|13:15:00|clinic",
                ),
            ])
            db.commit()
            schedules = [
                present_card(row)
                for row in db.query(ScheduleCard).filter_by(surgeon_id=chris.id, date=day).all()
            ]
            display = build_clinic_off_display(
                db, day, day,
                sched_map={chris.id: {day: schedules}},
                surgical_map={},
            )
            self.assertEqual(len(display["off_conflicts"]), 1)
            self.assertGreaterEqual(display["off_conflicts"][0].patient_count, 2)
            self.assertFalse(should_show_as_off(chris.id, day, display["off_map"], display["workloads"]))
        finally:
            db.close()

    def test_day_off_status_map_includes_pending(self):
        db = self.Session()
        try:
            chris = self._surgeon(db, "Chris", "Johnson")
            day = self._soon(3)
            db.add(DayOff(
                surgeon_id=chris.id,
                start_date=day,
                end_date=day,
                status="pending",
            ))
            db.commit()
            self._normalize(db, day)
            off_map = day_off_status_map(db, day, day)
            self.assertIn((chris.id, day), off_map)
            self.assertEqual(off_map[(chris.id, day)]["status"], "pending")
        finally:
            db.close()


if __name__ == "__main__":
    unittest.main()
