import os
import unittest
from datetime import date, time, timedelta

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("SECRET_KEY", "test-secret")

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models import Base, ClinicSchedule, DayOff, Location, Surgeon, SurgicalCase
from app.off_conflict_service import (
    detect_off_conflicts,
    should_show_as_off,
    build_clinic_off_display,
    day_off_status_map,
    schedule_matches_off_session,
)


class OffConflictServiceTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(bind=self.engine)
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

    def test_empty_clinic_on_off_shows_as_off_no_conflict(self):
        db = self.Session()
        try:
            chris = self._surgeon(db, "Chris", "Johnson")
            clinic = Location(name="WG Clinic", abbreviation="WG", location_type="clinic", is_active=True)
            db.add(clinic)
            db.flush()
            day = date.today() + timedelta(days=1)
            db.add(DayOff(
                surgeon_id=chris.id,
                start_date=day,
                end_date=day,
                status="approved",
                reason="Vacation",
            ))
            db.add(ClinicSchedule(
                surgeon_id=chris.id,
                location_id=clinic.id,
                date=day,
                session="full",
                assignment_type="assigned",
            ))
            db.commit()

            display = build_clinic_off_display(
                db, day, day,
                sched_map={chris.id: {day: db.query(ClinicSchedule).all()}},
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
            day = date.today() + timedelta(days=1)
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
            am = ClinicSchedule(
                surgeon_id=chris.id,
                location_id=hospital.id,
                date=day,
                session="am",
                assignment_type="assigned",
            )
            pm = ClinicSchedule(
                surgeon_id=chris.id,
                location_id=clinic.id,
                date=day,
                session="pm",
                assignment_type="assigned",
            )
            db.add_all([am, pm])
            db.commit()
            schedules = db.query(ClinicSchedule).order_by(ClinicSchedule.session).all()
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
            day = date.today() + timedelta(days=2)
            db.add(DayOff(
                surgeon_id=chris.id,
                start_date=day,
                end_date=day,
                status="pending",
                reason="Personal",
            ))
            db.add(SurgicalCase(
                surgeon_id=chris.id,
                date=day,
                start_time=time(8, 0),
                end_time=time(9, 0),
                patient_name="Test Patient",
                procedure="Lap chole",
                location_id=hospital.id,
                status="scheduled",
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
            day = date.today() + timedelta(days=3)
            db.add(DayOff(
                surgeon_id=chris.id,
                start_date=day,
                end_date=day,
                status="approved",
            ))
            db.add(ClinicSchedule(
                surgeon_id=chris.id,
                location_id=clinic.id,
                date=day,
                session="pm",
                assignment_type="assigned",
                notes="Desk fax ingest · 13:00 SMITH, JANE; 13:15 DOE, JOHN",
            ))
            db.commit()
            schedules = db.query(ClinicSchedule).all()
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
            day = date.today() + timedelta(days=4)
            db.add(DayOff(
                surgeon_id=chris.id,
                start_date=day,
                end_date=day,
                status="pending",
            ))
            db.commit()
            off_map = day_off_status_map(db, day, day)
            self.assertIn((chris.id, day), off_map)
            self.assertEqual(off_map[(chris.id, day)]["status"], "pending")
        finally:
            db.close()


if __name__ == "__main__":
    unittest.main()
