import os
import unittest
from datetime import date, time

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("SECRET_KEY", "test-secret")

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.day_off_card_normalization import backfill_day_off_card_links
from app.migrate_fax_ingest import create_applicable_view
from app.models import (
    AprimaCachedAppointment,
    Base,
    DayOff,
    Location,
    ScheduleCard,
    ScheduleCardActivity,
    Surgeon,
    SurgeonLocationSchedule,
)
from app.schedule_activity_normalization import backfill_normalized_schedule_activity, normalize_aprima_payload
from app.schedule_card_projection_service import card_grid_page_data
from app.schedule_card_service import materialize_master_schedule_cards


class ScheduleCardProjectionServiceTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        with self.engine.begin() as conn:
            create_applicable_view(conn)
        self.Session = sessionmaker(bind=self.engine)

    def tearDown(self):
        Base.metadata.drop_all(self.engine)
        self.engine.dispose()

    def test_projects_only_two_permanent_cards_and_counts_matching_cases(self):
        db = self.Session()
        try:
            surgeon = Surgeon(first_name="Alex", last_name="Smith", email="as@example.com", is_active=True, staff_type="physician")
            location = Location(name="Minneola OR", abbreviation="MN-OR", location_type="hospital", is_active=True)
            db.add_all([surgeon, location])
            db.commit()
            db.add(SurgeonLocationSchedule(surgeon_id=surgeon.id, day_of_week=0, session="am", location_id=location.id, assignment_type="assigned"))
            db.commit()
            materialize_master_schedule_cards(db, start=date(2026, 9, 14), end=date(2026, 9, 18))
            am_card = db.query(ScheduleCard).filter_by(surgeon_id=surgeon.id, date=date(2026, 9, 14), session="am").one()
            db.add(ScheduleCardActivity(
                schedule_card_id=am_card.id, surgeon_id=surgeon.id, location_id=location.id,
                activity_date=date(2026, 9, 14), session="am", activity_type="surgical",
                start_time=time(7, 15), patient_name="Patient", procedure="Procedure",
                source_system="fax", source_record_key="patient", identity_key="patient", is_active=True,
            ))
            db.commit()
            payload = card_grid_page_data(db, date(2026, 9, 14), date(2026, 9, 18))
            monday = payload["grid"][surgeon.id][date(2026, 9, 14)]
            self.assertEqual(set(monday), {"am", "pm"})
            self.assertEqual(monday["am"]["label"], "MN-OR")
            self.assertEqual(monday["am"]["count_label"], "1 case")
            self.assertEqual(len(monday["am"]["roster_cases"]), 1)
            self.assertTrue(monday["pm"]["is_na"])
            header = payload["hospital_headers"][date(2026, 9, 14)]
            self.assertEqual([(row["label"], row["count"]) for row in header], [("MN-OR", 1)])
            self.assertEqual(len(header[0]["roster_cases"]), 1)
        finally:
            db.close()

    def test_hospital_header_sql_count_excludes_clinic_rows(self):
        db = self.Session()
        try:
            surgeon = Surgeon(first_name="Alex", last_name="Smith", email="as@example.com", is_active=True)
            hospital = Location(name="Apopka OR", abbreviation="AP-OR", location_type="hospital", is_active=True)
            clinic = Location(name="Apopka Clinic", abbreviation="AP-OV", location_type="clinic", is_active=True)
            db.add_all([surgeon, hospital, clinic])
            db.commit()
            materialize_master_schedule_cards(db, start=date(2026, 9, 21), end=date(2026, 9, 25))
            am_card = db.query(ScheduleCard).filter_by(surgeon_id=surgeon.id, date=date(2026, 9, 21), session="am").one()
            am_card.baseline_location_id = hospital.id
            am_card.effective_location_id = hospital.id
            am_card.baseline_state = "assigned"
            am_card.effective_state = "assigned"
            pm_card = db.query(ScheduleCard).filter_by(surgeon_id=surgeon.id, date=date(2026, 9, 21), session="pm").one()
            pm_card.baseline_location_id = clinic.id
            pm_card.effective_location_id = clinic.id
            pm_card.baseline_state = "assigned"
            pm_card.effective_state = "assigned"
            db.add_all([
                ScheduleCardActivity(
                    schedule_card_id=am_card.id, surgeon_id=surgeon.id, location_id=hospital.id,
                    activity_date=date(2026, 9, 21), session="am", activity_type="surgical",
                    start_time=time(7, 15), patient_name="OR Patient", procedure="Procedure",
                    source_system="fax", source_record_key="or-patient", identity_key="or-patient", is_active=True,
                ),
                ScheduleCardActivity(
                    schedule_card_id=pm_card.id, surgeon_id=surgeon.id, location_id=clinic.id,
                    activity_date=date(2026, 9, 21), session="pm", activity_type="clinic",
                    start_time=time(8, 30), patient_name="Clinic Patient", procedure="Office visit",
                    source_system="fax_clinic", source_record_key="clinic-patient", identity_key="clinic-patient",
                    is_active=True,
                ),
            ])
            db.commit()

            payload = card_grid_page_data(db, date(2026, 9, 21), date(2026, 9, 25))
            header = payload["hospital_headers"][date(2026, 9, 21)]

            self.assertEqual([(row["label"], row["count"]) for row in header], [("AP-OR", 1)])
        finally:
            db.close()

    def test_approved_time_off_overlays_existing_card_without_creating_one(self):
        db = self.Session()
        try:
            surgeon = Surgeon(first_name="Alex", last_name="Smith", email="as@example.com", is_active=True, staff_type="physician")
            db.add(surgeon)
            db.commit()
            materialize_master_schedule_cards(db, start=date(2026, 9, 14), end=date(2026, 9, 18))
            db.add(DayOff(surgeon_id=surgeon.id, start_date=date(2026, 9, 14), end_date=date(2026, 9, 14), status="approved", is_full_day=True))
            db.commit()
            backfill_day_off_card_links(db)
            payload = card_grid_page_data(db, date(2026, 9, 14), date(2026, 9, 18))
            monday = payload["grid"][surgeon.id][date(2026, 9, 14)]
            self.assertTrue(monday["am"]["is_off"])
            self.assertTrue(monday["pm"]["is_off"])
            self.assertEqual(sum(len(day) for day in payload["grid"][surgeon.id].values()), 10)
        finally:
            db.close()

    def test_1145_or_case_after_1100_clinic_counts_on_pm_card(self):
        db = self.Session()
        try:
            surgeon = Surgeon(first_name="Lucy", last_name="Woodley", email="lw@example.com", is_active=True)
            clinic = Location(name="Apopka Clinic", abbreviation="AP-OV", location_type="clinic", is_active=True)
            hospital = Location(name="Apopka OR", abbreviation="AP-OR", location_type="hospital", is_active=True)
            db.add_all([surgeon, clinic, hospital])
            db.commit()
            db.add_all([
                SurgeonLocationSchedule(surgeon_id=surgeon.id, day_of_week=0, session="am", location_id=clinic.id, assignment_type="assigned"),
                SurgeonLocationSchedule(surgeon_id=surgeon.id, day_of_week=0, session="pm", location_id=hospital.id, assignment_type="assigned"),
            ])
            db.commit()
            materialize_master_schedule_cards(db, start=date(2026, 9, 21), end=date(2026, 9, 25))
            pm_card = db.query(ScheduleCard).filter_by(
                surgeon_id=surgeon.id, date=date(2026, 9, 21), session="pm"
            ).one()
            db.add(ScheduleCardActivity(
                schedule_card_id=pm_card.id, surgeon_id=surgeon.id, location_id=hospital.id,
                activity_date=date(2026, 9, 21), session="pm", activity_type="surgical",
                start_time=time(11, 45), patient_name="Case, Patient", procedure="Procedure",
                source_system="fax", source_record_key="case-patient", identity_key="case-patient",
                is_active=True,
            ))
            db.commit()
            am_card = db.query(ScheduleCard).filter_by(
                surgeon_id=surgeon.id, date=date(2026, 9, 21), session="am"
            ).one()
            db.add(ScheduleCardActivity(
                schedule_card_id=am_card.id,
                surgeon_id=surgeon.id,
                location_id=clinic.id,
                activity_date=date(2026, 9, 21),
                session="am",
                activity_type="clinic",
                start_time=time(11, 0),
                patient_name="Clinic, Patient",
                source_system="fax_clinic",
                source_record_key="test-clinic-1",
                identity_key="clinicpatient|11:00:00|clinic",
            ))
            db.commit()

            payload = card_grid_page_data(db, date(2026, 9, 21), date(2026, 9, 25))
            monday = payload["grid"][surgeon.id][date(2026, 9, 21)]
            self.assertEqual(monday["am"]["count_label"], "1 visit")
            self.assertEqual(monday["pm"]["count_label"], "1 case")
        finally:
            db.close()

    def test_aprima_clinic_patients_fill_existing_na_card(self):
        db = self.Session()
        try:
            surgeon = Surgeon(first_name="Jorge", last_name="Florin", email="jf@example.com", is_active=True)
            cbo = Location(name="CBO Clinic", abbreviation="CBO-OV", location_type="clinic", is_active=True)
            db.add_all([surgeon, cbo])
            db.commit()
            materialize_master_schedule_cards(db, start=date(2026, 9, 21), end=date(2026, 9, 25))
            for index in range(5):
                payload = {
                        "id": f"appt-{index}",
                        "date": "2026-09-23",
                        "start": f"13:{index * 10:02d}",
                        "patientName": f"Patient {index}",
                        "surgeonInitials": "JF",
                        "serviceSite": "Clermont Business Office",
                        "appointmentType": "Follow Up",
                }
                cached = AprimaCachedAppointment(
                    appointment_id=payload["id"], kind="patient", date=date(2026, 9, 23),
                    content_hash=payload["id"], payload_json="{}",
                )
                db.add(cached)
                normalize_aprima_payload(db, cached, payload)
            db.commit()

            payload = card_grid_page_data(db, date(2026, 9, 21), date(2026, 9, 25))
            card = payload["grid"][surgeon.id][date(2026, 9, 23)]["pm"]

            self.assertEqual(card["label"], "CBO-OV")
            self.assertEqual(card["count_label"], "5 visits")
            self.assertFalse(card["is_na"])
            self.assertEqual(len(card["roster_visits"]), 5)
            self.assertTrue(card["has_aprima"])
            self.assertEqual(sum(len(day) for day in payload["grid"][surgeon.id].values()), 10)
        finally:
            db.close()

    def test_aprima_and_fax_same_clinic_patient_count_once(self):
        db = self.Session()
        try:
            surgeon = Surgeon(first_name="Jorge", last_name="Florin", email="jf@example.com", is_active=True)
            cbo = Location(name="CBO Clinic", abbreviation="CBO-OV", location_type="clinic", is_active=True)
            db.add_all([surgeon, cbo])
            db.commit()
            db.add(SurgeonLocationSchedule(
                surgeon_id=surgeon.id,
                day_of_week=2,
                session="pm",
                location_id=cbo.id,
                assignment_type="assigned",
            ))
            db.commit()
            materialize_master_schedule_cards(db, start=date(2026, 9, 21), end=date(2026, 9, 25))
            card = db.query(ScheduleCard).filter_by(
                surgeon_id=surgeon.id, date=date(2026, 9, 23), session="pm"
            ).one()
            db.add(ScheduleCardActivity(
                schedule_card_id=card.id, surgeon_id=surgeon.id, location_id=cbo.id,
                activity_date=card.date, session="pm", activity_type="clinic",
                start_time=time(13, 0), patient_name="Same, Patient",
                source_system="fax_clinic", source_record_key="fax-test",
                identity_key="samepatient|13:00:00|clinic",
            ))
            payload = {
                    "id": "same-patient",
                    "date": "2026-09-23",
                    "start": "13:00",
                    "patientName": "Same, Patient",
                    "surgeonInitials": "JF",
                    "serviceSite": "Clermont Business Office",
                    "appointmentType": "Follow Up",
                }
            cached = AprimaCachedAppointment(
                appointment_id=payload["id"], kind="patient", date=card.date,
                content_hash="same-patient", payload_json="{}",
            )
            db.add(cached)
            normalize_aprima_payload(db, cached, payload)
            db.commit()

            payload = card_grid_page_data(db, date(2026, 9, 21), date(2026, 9, 25))
            card = payload["grid"][surgeon.id][date(2026, 9, 23)]["pm"]

            self.assertEqual(card["count_label"], "1 visit")
            self.assertEqual(len(card["roster_visits"]), 1)
        finally:
            db.close()

    def test_one_card_owns_many_lines(self):
        db = self.Session()
        try:
            surgeon = Surgeon(first_name="Alex", last_name="Smith", email="as@example.com", is_active=True, staff_type="physician")
            location = Location(name="Minneola OR", abbreviation="MN-OR", location_type="hospital", is_active=True)
            db.add_all([surgeon, location])
            db.commit()
            materialize_master_schedule_cards(db, start=date(2026, 9, 14), end=date(2026, 9, 14))
            card = db.query(ScheduleCard).filter_by(surgeon_id=surgeon.id, date=date(2026, 9, 14), session="am").one()
            other = db.query(ScheduleCard).filter_by(surgeon_id=surgeon.id, date=date(2026, 9, 14), session="pm").one()
            db.add_all([
                ScheduleCardActivity(
                    schedule_card_id=card.id, surgeon_id=surgeon.id, location_id=location.id,
                    activity_date=card.date, session="am", activity_type="surgical",
                    start_time=time(7, 30), patient_name="First", procedure="Case",
                    source_system="fax", source_record_key="line-1", identity_key="line-1",
                ),
                ScheduleCardActivity(
                    schedule_card_id=card.id, surgeon_id=surgeon.id, location_id=location.id,
                    activity_date=card.date, session="am", activity_type="clinic",
                    start_time=time(9, 0), patient_name="Second", procedure="Visit",
                    source_system="fax", source_record_key="line-2", identity_key="line-2",
                ),
            ])
            db.commit()
            db.expire_all()
            card = db.get(ScheduleCard, card.id)
            other = db.get(ScheduleCard, other.id)
            self.assertEqual(len(card.activities), 2)
            self.assertEqual({line.schedule_card.id for line in card.activities}, {card.id})
            self.assertEqual(other.activities, [])
        finally:
            db.close()


if __name__ == "__main__":
    unittest.main()
