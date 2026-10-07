import os
import unittest
from datetime import date, time
from unittest.mock import patch

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models import (
    Base,
    CallGroup,
    CallRotation,
    ClinicSchedule,
    DayOff,
    Location,
    Meeting,
    NativeScheduleAlert,
    ScheduleCard,
    ScheduleCardActivity,
    ScheduleCardWeek,
    Surgeon,
    SurgeonDayItem,
    SurgicalCase,
)
from app.native_home_service import build_native_home
from app.native_home_items import surgeons as native_surgeons


class FixedDate(date):
    @classmethod
    def today(cls):
        return cls(2026, 6, 4)


class NativeHomeContractTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(bind=self.engine)
        self.Session = sessionmaker(bind=self.engine)

    def tearDown(self):
        Base.metadata.drop_all(bind=self.engine)
        self.engine.dispose()

    def test_surgeon_picker_uses_positive_database_rank(self):
        db = self.Session()
        try:
            db.add_all([
                Surgeon(first_name="Chris", last_name="Johnson", sort_order=2, is_active=True),
                Surgeon(first_name="Robert", last_name="Florin", sort_order=1, is_active=True),
                Surgeon(first_name="Alex", last_name="Able", sort_order=0, is_active=True),
            ])
            db.commit()
            self.assertEqual(["Robert Florin", "Chris Johnson", "Alex Able"],
                             [row["name"] for row in native_surgeons(db)])
        finally:
            db.close()

    def test_native_home_payload_shape(self):
        db = self.Session()
        try:
            surgeon = Surgeon(
                first_name="Chris",
                last_name="Johnson",
                email="chris@example.com",
                staff_type="physician",
                sort_order=1,
                is_active=True,
            )
            off_surgeon = Surgeon(
                first_name="Alex",
                last_name="Smith",
                email="alex@example.com",
                staff_type="physician",
                sort_order=2,
                is_active=True,
            )
            location = Location(name="Altamonte Hosp", location_type="hospital", color="#0ea5e9", is_active=True)
            group = CallGroup(name="Winter Garden / Apopka", sort_order=1)
            db.add_all([surgeon, off_surgeon, location, group])
            db.flush()

            db.add_all([
                CallRotation(
                    call_group_id=group.id,
                    surgeon_id=surgeon.id,
                    date=date(2026, 6, 4),
                ),
                DayOff(
                    surgeon_id=surgeon.id,
                    start_date=date(2026, 6, 5),
                    end_date=date(2026, 6, 5),
                    reason="Vacation",
                    status="pending",
                    is_full_day=True,
                ),
                DayOff(
                    surgeon_id=off_surgeon.id,
                    start_date=date(2026, 6, 4),
                    end_date=date(2026, 6, 4),
                    reason="Day Off",
                    status="approved",
                    is_full_day=True,
                ),
                Meeting(
                    title="Dept Surgery",
                    date=date(2026, 6, 6),
                    start_time=time(7, 30),
                    end_time=time(8, 0),
                    location_text="Winter Garden",
                ),
                ClinicSchedule(
                    surgeon_id=surgeon.id,
                    location_id=location.id,
                    date=date(2026, 6, 4),
                    session="am",
                    assignment_type="assigned",
                ),
                SurgeonDayItem(
                    surgeon_id=surgeon.id,
                    date=date(2026, 6, 7),
                    start_time=time(14, 0),
                    title="Dentist",
                    sort_order=1,
                ),
                NativeScheduleAlert(
                    surgeon_id=surgeon.id,
                    title="Schedule updated",
                    body="Dept Surgery moved to 07:30.",
                    kind="schedule",
                ),
            ])
            db.commit()

            with patch("app.native_home_service.date", FixedDate), patch("app.native_home_service.practice_today", return_value=date(2026, 6, 4)):
                payload = build_native_home(db, surgeon, date(2026, 6, 4), date(2026, 6, 8))

            self.assertEqual(
                {
                    "surgeon",
                    "range",
                    "days",
                    "availability",
                    "requests",
                    "dayOffSections",
                    "callGroups",
                    "surgeons",
                    "callSchedule",
                    "alerts",
                },
                set(payload.keys()),
            )
            self.assertEqual(payload["surgeon"]["id"], surgeon.id)
            self.assertEqual(payload["range"], {"start": "2026-06-04", "end": "2026-06-08"})
            self.assertEqual(len(payload["days"]), 5)

            june_4 = payload["days"][0]
            self.assertEqual(
                {"date", "dayName", "dayShort", "dayFull", "items", "offSurgeons", "requestedOffSurgeons", "callAssignments"},
                set(june_4.keys()),
            )
            self.assertEqual(june_4["date"], "2026-06-04")
            self.assertEqual(june_4["callAssignments"][0]["initials"], "CJ")
            self.assertEqual(june_4["offSurgeons"][0]["initials"], "AS")
            self.assertTrue(any(item["type"] == "clinic" for item in june_4["items"]))

            june_5 = payload["days"][1]
            self.assertTrue(any(item["type"] == "dayoff" for item in june_5["items"]))
            self.assertTrue(any(request["status"] == "pending" for request in payload["requests"]))
            self.assertEqual(payload["callGroups"], [{"id": group.id, "name": group.name}])
            self.assertFalse(any(item["type"] == "patients" for day in payload["days"] for item in day["items"]))
            self.assertEqual(payload["alerts"]["unreadCount"], 1)
            self.assertEqual(payload["alerts"]["recent"][0]["title"], "Schedule updated")
            self.assertFalse(payload["alerts"]["recent"][0]["isRead"])
        finally:
            db.close()

    @patch("app.aprima_cache_service.patient_appointments_for_api")
    def test_native_home_includes_aprima_surgery_one_as_review_row(self, aprima_payload):
        db = self.Session()
        try:
            surgeon = Surgeon(
                first_name="Chris",
                last_name="Johnson",
                email="chris@example.com",
                staff_type="physician",
                sort_order=1,
                is_active=True,
            )
            db.add(surgeon)
            db.commit()

            aprima_payload.return_value = {
                "appointments": [
                    {
                        "id": "aprima-cbo-1",
                        "date": "2026-09-16",
                        "start": "11:00",
                        "end": "11:10",
                        "surgeonInitials": "CJ",
                        "surgeonName": "Chris Johnson",
                        "patientName": "Surgery One",
                        "appointmentType": "Office Visit",
                        "status": "Scheduled",
                        "reason": "Surgery One",
                        "serviceSite": "Clermont Office",
                        "room": "CBO",
                    }
                ],
            }

            payload = build_native_home(db, surgeon, date(2026, 9, 16), date(2026, 9, 16))

            items = payload["days"][0]["items"]
            row = next(item for item in items if item["id"] == "aprima-surg-aprima-cbo-1")
            self.assertEqual(row["type"], "surgery")
            self.assertEqual(row["source"], "aprima")
            self.assertTrue(row["readOnly"])
            self.assertTrue(row["needsReview"])
            self.assertEqual(row["location"], "Surgery One")
            self.assertEqual(row["color"], "#dc2626")
            self.assertEqual(row["notes"], "Aprima review needed")
        finally:
            db.close()

    @patch("app.aprima_cache_service.patient_appointments_for_api")
    def test_master_cards_and_epic_cases_survive_approved_off(self, aprima_payload):
        aprima_payload.return_value = {"appointments": []}
        db = self.Session()
        try:
            surgeon = Surgeon(first_name="Chris", last_name="Johnson", is_active=True)
            assistant = Surgeon(first_name="Alex", last_name="Smith", is_active=True)
            hospital = Location(name="Altamonte Hospital", abbreviation="ALT", location_type="hospital")
            clinic = Location(name="Lake Mary Clinic", abbreviation="LM", location_type="clinic")
            db.add_all([surgeon, assistant, hospital, clinic])
            db.flush()
            week = ScheduleCardWeek(surgeon_id=surgeon.id, week_start=date(2026, 10, 5))
            db.add(week)
            db.flush()
            am = ScheduleCard(week_id=week.id, surgeon_id=surgeon.id, date=date(2026, 10, 5),
                              session="am", baseline_state="assigned", effective_state="assigned",
                              baseline_location_id=hospital.id, effective_location_id=hospital.id)
            pm = ScheduleCard(week_id=week.id, surgeon_id=surgeon.id, date=date(2026, 10, 5),
                              session="pm", baseline_state="na", effective_state="na")
            db.add_all([am, pm])
            db.flush()
            case = SurgicalCase(surgeon_id=surgeon.id, assisting_surgeon_id=assistant.id,
                                date=date(2026, 10, 5), start_time=time(8, 30), end_time=time(9, 30),
                                patient_name="Test Patient", procedure="Test procedure", location_id=hospital.id,
                                schedule_card_id=am.id, status="scheduled")
            db.add(case)
            db.add(DayOff(surgeon_id=surgeon.id, start_date=date(2026, 10, 5),
                          end_date=date(2026, 10, 5), reason="Vacation", status="approved", is_full_day=True))
            db.commit()

            payload = build_native_home(db, surgeon, date(2026, 10, 5), date(2026, 10, 5))
            items = payload["days"][0]["items"]
            self.assertEqual(["OFF", "OFF"], [item["title"] for item in items if item["id"].startswith("card-")])
            self.assertTrue(next(item for item in items if item["id"] == f"card-{am.id}")["needsReview"])
            surgery = next(item for item in items if item["id"] == f"surg-{case.id}")
            self.assertEqual(surgery["title"], "Test Patient")
            self.assertTrue(surgery["needsReview"])
            self.assertEqual(surgery["rawId"], case.id)
            self.assertEqual(len([item for item in items if item["type"] == "surgery"]), 1)

            assist_items = build_native_home(db, assistant, date(2026, 10, 5), date(2026, 10, 5))["days"][0]["items"]
            assist = next(item for item in assist_items if item["type"] == "surgery")
            self.assertIn("Assisting", assist["subtitle"])
            self.assertTrue(assist["readOnly"])
        finally:
            db.close()

    @patch("app.aprima_cache_service.patient_appointments_for_api")
    def test_no_call_is_not_a_day_off_or_a_case_conflict(self, aprima_payload):
        aprima_payload.return_value = {"appointments": []}
        db = self.Session()
        try:
            surgeon = Surgeon(first_name="Chris", last_name="Johnson", is_active=True)
            hospital = Location(name="Altamonte Hospital", abbreviation="ALT", location_type="hospital")
            db.add_all([surgeon, hospital])
            db.flush()
            week = ScheduleCardWeek(surgeon_id=surgeon.id, week_start=date(2026, 10, 5))
            db.add(week)
            db.flush()
            card = ScheduleCard(week_id=week.id, surgeon_id=surgeon.id, date=date(2026, 10, 6),
                                session="am", baseline_state="assigned", effective_state="assigned",
                                baseline_location_id=hospital.id, effective_location_id=hospital.id)
            db.add_all([
                card,
                SurgicalCase(surgeon_id=surgeon.id, date=date(2026, 10, 6), start_time=time(9),
                             end_time=time(10), patient_name="Test Patient", procedure="Test procedure",
                             location_id=hospital.id, status="scheduled"),
                DayOff(surgeon_id=surgeon.id, start_date=date(2026, 10, 6), end_date=date(2026, 10, 6),
                       reason="No Call", status="approved", is_full_day=True),
            ])
            db.commit()

            items = build_native_home(db, surgeon, date(2026, 10, 6), date(2026, 10, 6))["days"][0]["items"]
            self.assertEqual("ALT", next(item for item in items if item["id"] == f"card-{card.id}")["title"])
            self.assertFalse(next(item for item in items if item["type"] == "surgery")["needsReview"])
            self.assertEqual("No Call", next(item for item in items if item["type"] == "dayoff")["title"])
        finally:
            db.close()

    @patch("app.aprima_cache_service.patient_appointments_for_api")
    def test_cards_carry_sql_case_and_visit_counts(self, aprima_payload):
        aprima_payload.return_value = {"appointments": []}
        db = self.Session()
        try:
            surgeon = Surgeon(first_name="Chris", last_name="Johnson", is_active=True)
            hospital = Location(name="Altamonte Hospital", abbreviation="ALT", location_type="hospital")
            clinic = Location(name="Lake Mary Clinic", abbreviation="LM", location_type="clinic")
            db.add_all([surgeon, hospital, clinic])
            db.flush()
            week = ScheduleCardWeek(surgeon_id=surgeon.id, week_start=date(2026, 10, 5))
            db.add(week)
            db.flush()
            am = ScheduleCard(week_id=week.id, surgeon_id=surgeon.id, date=date(2026, 10, 6),
                              session="am", baseline_state="assigned", effective_state="assigned",
                              baseline_location_id=hospital.id, effective_location_id=hospital.id)
            pm = ScheduleCard(week_id=week.id, surgeon_id=surgeon.id, date=date(2026, 10, 6),
                              session="pm", baseline_state="assigned", effective_state="assigned",
                              baseline_location_id=clinic.id, effective_location_id=clinic.id)
            db.add_all([am, pm])
            db.flush()
            db.add(SurgicalCase(surgeon_id=surgeon.id, date=date(2026, 10, 6), start_time=time(8),
                                end_time=time(9), patient_name="Test Patient", procedure="Test procedure",
                                location_id=hospital.id, schedule_card_id=am.id, status="scheduled"))
            for index, key in enumerate(["a", "b", "b"]):
                db.add(ScheduleCardActivity(
                    schedule_card_id=pm.id, surgeon_id=surgeon.id, location_id=clinic.id,
                    activity_date=date(2026, 10, 6), session="pm", activity_type="clinic",
                    patient_name="Test Visit", source_system="test", source_record_key=f"k{index}",
                    identity_key=key,
                ))
            db.commit()

            items = build_native_home(db, surgeon, date(2026, 10, 6), date(2026, 10, 6))["days"][0]["items"]
            am_item = next(item for item in items if item["id"] == f"card-{am.id}")
            pm_item = next(item for item in items if item["id"] == f"card-{pm.id}")
            self.assertEqual((1, 0), (am_item["caseCount"], am_item["visitCount"]))
            self.assertEqual((0, 2), (pm_item["caseCount"], pm_item["visitCount"]))
            self.assertEqual((am.id, pm.id), (am_item["cardId"], pm_item["cardId"]))
            surgery = next(item for item in items if item["type"] == "surgery")
            self.assertEqual(am.id, surgery["cardId"])

            stored_on_pm = SurgicalCase(surgeon_id=surgeon.id, date=date(2026, 10, 6), start_time=time(11),
                                        end_time=time(12), patient_name="Late Patient", procedure="Test",
                                        location_id=clinic.id, schedule_card_id=pm.id, status="scheduled")
            db.add(stored_on_pm)
            db.commit()
            items = build_native_home(db, surgeon, date(2026, 10, 6), date(2026, 10, 6))["days"][0]["items"]
            self.assertEqual(pm.id, next(item for item in items if item["id"] == f"surg-{stored_on_pm.id}")["cardId"])
            self.assertEqual(1, next(item for item in items if item["id"] == f"card-{pm.id}")["caseCount"])
        finally:
            db.close()


if __name__ == "__main__":
    unittest.main()
