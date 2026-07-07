import os
import unittest
from datetime import date, time, timedelta

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("SECRET_KEY", "test-secret")

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models import (
    Base,
    ClinicGroup,
    ClinicGroupMember,
    ClinicSchedule,
    DayOff,
    Location,
    Meeting,
    MeetingAttendee,
    Surgeon,
    SurgicalBlock,
    SurgicalCase,
)
from app.scheduling_guardrails_service import (
    clinic_group_day_off_findings,
    scheduler_safe_rows,
    surgical_case_warning_messages,
)


class SchedulingGuardrailsTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(bind=self.engine)
        self.Session = sessionmaker(bind=self.engine)

    def tearDown(self):
        Base.metadata.drop_all(bind=self.engine)
        self.engine.dispose()

    def test_clinic_group_capacity_warns_when_limit_reached(self):
        db = self.Session()
        try:
            request_day = date.today() + timedelta(days=14)
            group = ClinicGroup(name="Winter Garden", abbreviation="WG", max_approved_off_per_day=2, is_active=True)
            first = self._surgeon(db, "Chris", "Johnson", 1)
            second = self._surgeon(db, "Alex", "Schroeder", 2)
            requester = self._surgeon(db, "Lucy", "Woodley", 3)
            db.add(group)
            db.flush()
            db.add_all([
                ClinicGroupMember(clinic_group_id=group.id, surgeon_id=first.id),
                ClinicGroupMember(clinic_group_id=group.id, surgeon_id=second.id),
                ClinicGroupMember(clinic_group_id=group.id, surgeon_id=requester.id),
                DayOff(surgeon_id=first.id, start_date=request_day, end_date=request_day, status="approved"),
                DayOff(surgeon_id=second.id, start_date=request_day, end_date=request_day, status="approved"),
            ])
            db.commit()

            findings = clinic_group_day_off_findings(db, requester, request_day, request_day)

            self.assertEqual(len(findings), 1)
            self.assertIn("Winter Garden allows 2", findings[0].message)
            self.assertIn("Shannon will review", findings[0].surgeon_message)
        finally:
            db.close()

    def test_surgical_block_warnings_and_scheduler_safe_rows_hide_phi(self):
        db = self.Session()
        try:
            surgeon = self._surgeon(db, "Jorge", "Florin", 1)
            hospital = Location(name="Demo OR", abbreviation="DOR", location_type="hospital", is_active=True)
            clinic = Location(name="Demo Clinic", abbreviation="DCL", location_type="clinic", is_active=True)
            db.add_all([hospital, clinic])
            db.flush()
            case_day = date.today() + timedelta(days=10)
            db.add(SurgicalBlock(
                surgeon_id=surgeon.id,
                location_id=hospital.id,
                day_of_week=case_day.weekday(),
                start_time=time(7, 30),
                end_time=time(12, 0),
                recurrence="weekly",
            ))
            db.add(ClinicSchedule(
                surgeon_id=surgeon.id,
                location_id=clinic.id,
                date=case_day,
                session="am",
                assignment_type="assigned",
            ))
            meeting = Meeting(title="Assigned Meeting", date=case_day, start_time=time(10, 0), end_time=time(11, 0))
            db.add(meeting)
            db.flush()
            db.add(MeetingAttendee(meeting_id=meeting.id, surgeon_id=surgeon.id))
            db.add(SurgicalCase(
                surgeon_id=surgeon.id,
                date=case_day,
                start_time=time(15, 0),
                end_time=time(15, 30),
                patient_name="Hidden Patient",
                patient_dob="1/1/1960",
                patient_phone="4075550100",
                procedure="Demo procedure",
                location_id=hospital.id,
                status="scheduled",
            ))
            db.add(SurgicalCase(
                surgeon_id=surgeon.id,
                date=case_day,
                start_time=time(15, 10),
                end_time=time(15, 40),
                patient_name="Overlap Patient",
                procedure="Second demo procedure",
                location_id=hospital.id,
                status="scheduled",
            ))
            db.commit()

            warnings = surgical_case_warning_messages(
                db,
                surgeon.id,
                case_day,
                time(15, 0),
                time(15, 30),
                hospital.id,
            )
            self.assertTrue(any("Outside surgical block" in warning for warning in warnings))

            rows = scheduler_safe_rows(db, case_day, case_day)
            self.assertEqual(len(rows), 2)
            self.assertEqual(rows[0]["procedure"], "Demo procedure")
            self.assertNotIn("patient_name", rows[0])
            self.assertNotIn("patient_dob", rows[0])
            self.assertNotIn("patient_phone", rows[0])
            all_safe_warning_text = " ".join(" ".join(row["warnings"]) for row in rows)
            self.assertNotIn("Hidden Patient", all_safe_warning_text)
            self.assertNotIn("Overlap Patient", all_safe_warning_text)
        finally:
            db.close()

    def _surgeon(self, db, first_name, last_name, sort_order):
        surgeon = Surgeon(
            first_name=first_name,
            last_name=last_name,
            email=f"{first_name.lower()}.{last_name.lower()}@example.com",
            staff_type="physician",
            sort_order=sort_order,
            is_active=True,
        )
        db.add(surgeon)
        db.flush()
        return surgeon


if __name__ == "__main__":
    unittest.main()
