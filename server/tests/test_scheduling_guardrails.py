import os
import unittest
from datetime import date, time, timedelta

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("SECRET_KEY", "test-secret")

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models import (
    Base,
    CallGroup,
    CallRotation,
    ClinicGroup,
    ClinicGroupMember,
    DayOff,
    Location,
    Meeting,
    MeetingAttendee,
    ScheduleCard,
    ScheduleCardActivity,
    ScheduleCardWeek,
    Surgeon,
    SurgicalBlock,
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
            group = ClinicGroup(
                name="Winter Garden",
                abbreviation="WG",
                group_type="people",
                enforce_day_off_limit=True,
                max_approved_off_per_day=2,
                is_active=True,
            )
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
            self.assertIn("Winter Garden allows 2 approved members", findings[0].message)
            self.assertIn("Shannon will review", findings[0].surgeon_message)
        finally:
            db.close()

    def test_clinic_group_skips_capacity_when_limit_disabled(self):
        db = self.Session()
        try:
            request_day = date.today() + timedelta(days=14)
            group = ClinicGroup(
                name="Rules Only",
                abbreviation="RO",
                group_type="people",
                enforce_day_off_limit=False,
                max_approved_off_per_day=1,
                is_active=True,
            )
            first = self._surgeon(db, "Chris", "Johnson", 1)
            requester = self._surgeon(db, "Lucy", "Woodley", 2)
            db.add(group)
            db.flush()
            db.add_all([
                ClinicGroupMember(clinic_group_id=group.id, surgeon_id=first.id),
                ClinicGroupMember(clinic_group_id=group.id, surgeon_id=requester.id),
                DayOff(surgeon_id=first.id, start_date=request_day, end_date=request_day, status="approved"),
            ])
            db.commit()

            findings = clinic_group_day_off_findings(db, requester, request_day, request_day)
            self.assertEqual(findings, [])
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
            self._card(db, surgeon, case_day, "am", clinic.id)
            meeting = Meeting(title="Assigned Meeting", date=case_day, start_time=time(10, 0), end_time=time(11, 0))
            db.add(meeting)
            db.flush()
            db.add(MeetingAttendee(meeting_id=meeting.id, surgeon_id=surgeon.id))
            card = self._card(db, surgeon, case_day, "pm", hospital.id)
            self._line(
                db, card, start=time(15, 0), end=time(15, 30),
                patient="Hidden Patient", procedure="Demo procedure",
                location_id=hospital.id, key="hidden",
            )
            self._line(
                db, card, start=time(15, 10), end=time(15, 40),
                patient="Overlap Patient", procedure="Second demo procedure",
                location_id=hospital.id, key="overlap",
            )
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
            self.assertEqual([row["procedure"] for row in rows], ["Demo procedure", "Second demo procedure"])
            self.assertNotIn("Old list procedure", [row["procedure"] for row in rows])
            self.assertNotIn("patient_name", rows[0])
            self.assertNotIn("patient_dob", rows[0])
            self.assertNotIn("patient_phone", rows[0])
            all_safe_warning_text = " ".join(" ".join(row["warnings"]) for row in rows)
            self.assertNotIn("Hidden Patient", all_safe_warning_text)
            self.assertNotIn("Overlap Patient", all_safe_warning_text)
        finally:
            db.close()

    def test_block_or_cases_do_not_false_warn(self):
        """Desk-linked Block OR cases must not warn about missing block / own block / grid OR."""
        from app.models import ORBlockAssignment, ORBlockInstance

        db = self.Session()
        try:
            surgeon = self._surgeon(db, "Jorge", "Florin", 1)
            ap_or = Location(name="Apopka OR", abbreviation="AP-OR", location_type="hospital", is_active=True)
            ap_cl = Location(name="Apopka Clinic", abbreviation="AP-CL", location_type="clinic", is_active=True)
            db.add_all([ap_or, ap_cl])
            db.flush()
            case_day = date(2026, 7, 27)
            block = ORBlockInstance(
                location_id=ap_or.id,
                date=case_day,
                session="am",
                start_time=time(8, 30),
                end_time=time(11, 15),
                status="assigned",
            )
            db.add(block)
            db.flush()
            db.add(ORBlockAssignment(
                block_instance_id=block.id,
                surgeon_id=surgeon.id,
                start_time=time(8, 30),
                case_count=2,
            ))
            self._card(db, surgeon, case_day, "pm", ap_cl.id)
            card = self._card(db, surgeon, case_day, "am", ap_or.id)
            self._line(
                db, card, start=time(8, 30), patient="Sheffield, Martin",
                procedure="Hernia", location_id=ap_or.id, block_id=block.id, key="hernia",
            )
            self._line(
                db, card, start=time(9, 45), patient="Cruz Mejia, Cristina",
                procedure="Incisional", location_id=ap_or.id, block_id=block.id, key="incisional",
            )
            db.commit()

            for start in (time(8, 30), time(9, 45)):
                warnings = surgical_case_warning_messages(
                    db,
                    surgeon.id,
                    case_day,
                    start,
                    None,
                    ap_or.id,
                    or_block_instance_id=block.id,
                )
                text = " | ".join(warnings)
                self.assertNotIn("No surgical block", text)
                self.assertNotIn("Clinic at Apopka OR", text)
                self.assertNotIn("OR block at Apopka OR", text)

            rows = scheduler_safe_rows(db, case_day, case_day)
            self.assertEqual(len(rows), 2)
            self.assertNotIn("Old list procedure", [row["procedure"] for row in rows])
            for row in rows:
                self.assertEqual(row["warnings"], [])
        finally:
            db.close()

    def test_on_call_is_not_a_surgical_case_warning(self):
        from app.models import ORBlockAssignment, ORBlockInstance

        db = self.Session()
        try:
            surgeon = self._surgeon(db, "Lucy", "Woodley", 1)
            hospital = Location(name="Winter Garden OR", abbreviation="WG-OR", location_type="hospital", is_active=True)
            group = CallGroup(name="Winter Garden / Apopka / Minneola Hospital")
            db.add_all([hospital, group])
            db.flush()
            case_day = date(2026, 9, 16)
            db.add(CallRotation(surgeon_id=surgeon.id, call_group_id=group.id, date=case_day))
            block = ORBlockInstance(
                location_id=hospital.id,
                date=case_day,
                session="am",
                start_time=time(7, 0),
                end_time=time(12, 0),
                status="assigned",
            )
            db.add(block)
            db.flush()
            db.add(ORBlockAssignment(
                block_instance_id=block.id,
                surgeon_id=surgeon.id,
                start_time=time(7, 0),
                case_count=0,
            ))
            db.commit()

            warnings = surgical_case_warning_messages(
                db,
                surgeon.id,
                case_day,
                time(8, 0),
                None,
                hospital.id,
                or_block_instance_id=block.id,
            )
            joined = " ".join(warnings).lower()
            self.assertNotIn("on call", joined)
            self.assertNotIn("on-call", joined)
        finally:
            db.close()

    def test_running_late_from_block_to_1pm_clinic_is_not_a_warning(self):
        from app.models import ORBlockAssignment, ORBlockInstance
        from app.rules_engine.buffer_checkers import (
            check_buffer_surgery_to_clinic,
            check_location_drive_time,
        )

        db = self.Session()
        try:
            surgeon = self._surgeon(db, "Chris", "Johnson", 1)
            hospital = Location(name="Winter Garden OR", abbreviation="WG-OR", location_type="hospital", is_active=True)
            clinic = Location(name="Winter Garden Clinic", abbreviation="WG-OV", location_type="clinic", is_active=True)
            db.add_all([hospital, clinic])
            db.flush()
            case_day = date.today() + timedelta(days=14)
            block = ORBlockInstance(
                location_id=hospital.id,
                date=case_day,
                session="am",
                start_time=time(7, 0),
                end_time=time(12, 0),
                status="assigned",
            )
            db.add(block)
            db.flush()
            db.add(ORBlockAssignment(
                block_instance_id=block.id,
                surgeon_id=surgeon.id,
                start_time=time(7, 0),
                case_count=1,
            ))
            self._card(db, surgeon, case_day, "pm", clinic.id)
            db.commit()

            target = {
                "type": "surgical_case",
                "date": case_day,
                "start_time": time(11, 30),
                "end_time": time(12, 30),
                "location_id": hospital.id,
            }
            buffers = list(check_buffer_surgery_to_clinic(
                surgeon.id, case_day, case_day, db, {"minutes": 30}, None, target,
            ))
            drives = list(check_location_drive_time(
                surgeon.id, case_day, case_day, db, {"minutes_between_sites": 60}, None, target,
            ))
            self.assertEqual(buffers, [])
            self.assertEqual(drives, [])

            warnings = surgical_case_warning_messages(
                db,
                surgeon.id,
                case_day,
                time(11, 30),
                time(12, 30),
                hospital.id,
                or_block_instance_id=block.id,
            )
            joined = " ".join(warnings).lower()
            self.assertNotIn("need ", joined)
            self.assertNotIn("drive", joined)
            self.assertNotIn("between last surgery and clinic", joined)
        finally:
            db.close()

    def _card(self, db, surgeon, day, session, location_id):
        monday = day - timedelta(days=day.weekday())
        week = (
            db.query(ScheduleCardWeek)
            .filter_by(surgeon_id=surgeon.id, week_start=monday)
            .one_or_none()
        )
        if week is None:
            week = ScheduleCardWeek(surgeon_id=surgeon.id, week_start=monday, master_revision="test")
            db.add(week)
            db.flush()
        card = ScheduleCard(
            week_id=week.id,
            surgeon_id=surgeon.id,
            date=day,
            session=session,
            baseline_state="assigned",
            effective_state="assigned",
            baseline_location_id=location_id,
            effective_location_id=location_id,
            source="master",
        )
        db.add(card)
        db.flush()
        return card

    def _line(self, db, card, *, start, patient, procedure, location_id, key, end=None, block_id=None):
        row = ScheduleCardActivity(
            schedule_card_id=card.id,
            surgeon_id=card.surgeon_id,
            location_id=location_id,
            activity_date=card.date,
            session=card.session,
            activity_type="surgical",
            start_time=start,
            end_time=end,
            patient_name=patient,
            procedure=procedure,
            source_system="block_or" if block_id else "fax",
            source_record_key=key,
            identity_key=key,
            or_block_instance_id=block_id,
            is_active=True,
        )
        db.add(row)
        db.flush()
        return row

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
