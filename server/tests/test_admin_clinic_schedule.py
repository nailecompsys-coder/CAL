import os
import unittest
from datetime import date, time, timedelta
from types import SimpleNamespace

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.admin_clinic_schedule_action_service import assign_clinic, copy_clinic_week
from app.admin_clinic_schedule_page_service import (
    aggregate_assigned_or_blocks,
    clinic_schedule_sort_key,
    open_block_day_slots,
    page_data,
)
from app.migrate_location_admin_fields import normalize_office_location_name
from app.models import Base, ClinicSchedule, Location, Surgeon
from app.or_block_service import BlockORCreateInput, assign_block, create_or_blocks

class AdminClinicScheduleTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(bind=self.engine)
        self.Session = sessionmaker(bind=self.engine)

    def tearDown(self):
        Base.metadata.drop_all(bind=self.engine)
        self.engine.dispose()

    def test_clinic_schedule_sort_key_places_am_pm_then_full(self):
        rows = [
            ClinicSchedule(id=10, session="pm"),
            ClinicSchedule(id=11, session="full"),
            ClinicSchedule(id=12, session="am"),
        ]

        ordered = sorted(rows, key=clinic_schedule_sort_key)

        self.assertEqual([row.session for row in ordered], ["am", "pm", "full"])

    def test_copy_clinic_week_filters_to_selected_surgeon_only(self):
        db = self.Session()
        try:
            chris = self._surgeon(db, "Chris", "Johnson")
            alex = self._surgeon(db, "Alex", "Schroeder")
            clinic = Location(name="Winter Garden Clinic", abbreviation="WG", location_type="clinic", is_active=True)
            db.add(clinic)
            db.flush()

            today = date.today()
            src_start = today - timedelta(days=today.weekday())
            db.add_all([
                ClinicSchedule(surgeon_id=chris.id, location_id=clinic.id, date=src_start, session="am"),
                ClinicSchedule(surgeon_id=alex.id, location_id=clinic.id, date=src_start, session="pm"),
            ])
            db.commit()

            result = copy_clinic_week(db, 0, str(chris.id))

            self.assertTrue(result["ok"])
            self.assertEqual(result["created"], 1)
            next_week = src_start + timedelta(days=7)
            copied = db.query(ClinicSchedule).filter(ClinicSchedule.date == next_week).all()
            self.assertEqual(len(copied), 1)
            self.assertEqual(copied[0].surgeon_id, chris.id)
            self.assertEqual(copied[0].session, "am")
        finally:
            db.close()

    def test_edit_existing_assignment_by_id_does_not_leave_old_session(self):
        db = self.Session()
        try:
            surgeon = self._surgeon(db, "Chris", "Johnson")
            clinic = Location(name="Winter Garden Clinic", abbreviation="WG", location_type="clinic", is_active=True)
            hospital = Location(name="Winter Garden OR", abbreviation="WG-OR", location_type="hospital", is_active=True)
            db.add_all([clinic, hospital])
            db.flush()

            schedule_date = date(2026, 7, 8)
            existing = ClinicSchedule(
                surgeon_id=surgeon.id,
                location_id=clinic.id,
                date=schedule_date,
                session="am",
                assignment_type="assigned",
                notes="old note",
            )
            db.add(existing)
            db.commit()
            existing_id = existing.id

            conflicts = assign_clinic(
                db,
                schedule_date,
                surgeon.id,
                str(hospital.id),
                "pm",
                "new note",
                schedule_id=existing_id,
            )

            self.assertEqual(conflicts, [])
            rows = db.query(ClinicSchedule).filter(
                ClinicSchedule.surgeon_id == surgeon.id,
                ClinicSchedule.date == schedule_date,
            ).all()
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0].location_id, hospital.id)
            self.assertEqual(rows[0].session, "pm")
            self.assertEqual(rows[0].notes, "new note")
        finally:
            db.close()

    def test_location_name_normalization_changes_office_word_to_clinic(self):
        self.assertEqual(normalize_office_location_name("Winter Garden Office"), "Winter Garden Clinic")
        self.assertEqual(normalize_office_location_name("Office"), "Clinic")
        self.assertEqual(normalize_office_location_name("Main Clinic"), "Main Clinic")

    def test_page_data_indexes_every_block_assignment_by_surgeon(self):
        db = self.Session()
        try:
            hospital = Location(
                name="Advent Winter Garden",
                abbreviation="WG",
                location_type="hospital",
                is_active=True,
            )
            db.add(hospital)
            chris = self._surgeon(db, "Chris", "Johnson")
            jason = self._surgeon(db, "Jason", "Boardman")
            db.flush()
            monday = date.today() - timedelta(days=date.today().weekday())
            block_id = create_or_blocks(
                db,
                BlockORCreateInput(
                    name="Open AM",
                    start_date=monday,
                    end_date=monday,
                    weekdays=[monday.weekday()],
                    location_ids=[hospital.id],
                    session="am",
                    start_time=time(7, 0),
                    end_time=time(12, 0),
                    recurrence="once",
                ),
            )["instance_ids"][0]
            assign_block(db, block_id, chris.id, assigned_start_time=time(7, 0), case_count=1)
            assign_block(db, block_id, jason.id, assigned_start_time=time(9, 0), case_count=2)

            data = page_data(db, week_offset=0)
            chris_blocks = data["assigned_or_blocks"].get(chris.id, {}).get(monday, [])
            jason_blocks = data["assigned_or_blocks"].get(jason.id, {}).get(monday, [])

            self.assertEqual(len(chris_blocks), 1)
            self.assertEqual(len(jason_blocks), 1)
            self.assertEqual(chris_blocks[0]["surgeonId"], chris.id)
            self.assertEqual(chris_blocks[0]["caseCount"], 1)
            self.assertEqual(jason_blocks[0]["surgeonId"], jason.id)
            self.assertEqual(jason_blocks[0]["caseCount"], 2)
            self.assertEqual(jason_blocks[0]["assignedStart"], "09:00")
            self.assertEqual(jason_blocks[0]["pillLabel"], "WG 0900 2 Cases")
            self.assertEqual(jason_blocks[0]["session"], "am")
            self.assertEqual(len(jason_blocks[0]["segments"]), 1)
        finally:
            db.close()

    def test_aggregate_assigned_or_blocks_merges_same_location_session(self):
        merged = aggregate_assigned_or_blocks([
            {
                "id": 1,
                "date": "2026-07-13",
                "session": "am",
                "surgeonId": 7,
                "locationId": 3,
                "location": "Winter Garden OR",
                "locationAbbreviation": "WG-OR",
                "locationColor": "#E48EA6",
                "assignedStart": "09:00",
                "caseCount": 2,
                "assignmentNote": "",
                "assignmentLabel": "WG-OR - 09:00 - 2 Cases",
                "assignmentId": 11,
            },
            {
                "id": 1,
                "date": "2026-07-13",
                "session": "am",
                "surgeonId": 7,
                "locationId": 3,
                "location": "Winter Garden OR",
                "locationAbbreviation": "WG-OR",
                "locationColor": "#E48EA6",
                "assignedStart": "07:00",
                "caseCount": 1,
                "assignmentNote": "",
                "assignmentLabel": "WG-OR - 07:00 - 1 Case",
                "assignmentId": 10,
            },
            {
                "id": 2,
                "date": "2026-07-13",
                "session": "pm",
                "surgeonId": 7,
                "locationId": 3,
                "location": "Winter Garden OR",
                "locationAbbreviation": "WG-OR",
                "locationColor": "#E48EA6",
                "assignedStart": "13:00",
                "caseCount": 1,
                "assignmentNote": "late",
                "assignmentLabel": "WG-OR - 13:00 - 1 Case",
                "assignmentId": 12,
            },
        ])
        self.assertEqual(len(merged), 2)
        am = next(row for row in merged if row["session"] == "am")
        pm = next(row for row in merged if row["session"] == "pm")
        self.assertEqual(am["caseCount"], 3)
        self.assertEqual(am["assignedStart"], "07:00")
        self.assertEqual(am["pillLabel"], "WG-OR 0700 3 Cases")
        self.assertEqual(len(am["segments"]), 2)
        self.assertEqual(pm["pillLabel"], "WG-OR 1300 1 Case")
        self.assertEqual(pm["assignmentNote"], "late")

    def test_open_block_day_slots_one_pill_per_or(self):
        hospitals = [
            SimpleNamespace(id=1, abbreviation="AL-OR", name="Altamonte OR", color="#79CDBD"),
            SimpleNamespace(id=2, abbreviation="AP-OR", name="Apopka OR", color="#C4B5FD"),
            SimpleNamespace(id=3, abbreviation="MN-OR", name="Minneola OR", color="#FDBA74"),
            SimpleNamespace(id=4, abbreviation="WG-OR", name="Winter Garden OR", color="#E48EA6"),
        ]
        day = date(2026, 7, 11)
        by_day = {
            day: {
                3: [
                    {
                        "id": 50,
                        "start": "07:00",
                        "end": "12:00",
                        "status": "open",
                        "caseCount": 0,
                    }
                ],
                4: [
                    {
                        "id": 51,
                        "start": "07:00",
                        "end": "12:00",
                        "status": "assigned",
                        "caseCount": 2,
                    },
                    {
                        "id": 52,
                        "start": "09:00",
                        "end": "12:00",
                        "status": "assigned",
                        "caseCount": 1,
                    },
                ],
            }
        }
        slots = open_block_day_slots(hospitals, by_day, day)
        self.assertEqual(len(slots), 4)
        self.assertEqual(slots[0]["status"], "empty")
        self.assertIsNone(slots[0]["blockId"])
        mn = slots[2]
        self.assertEqual(mn["locationAbbreviation"], "MN-OR")
        self.assertEqual(mn["timeLabel"], "7-12")
        self.assertEqual(mn["caseCount"], 0)
        self.assertEqual(mn["blockId"], 50)
        wg = slots[3]
        self.assertEqual(wg["timeLabel"], "7-12")
        self.assertEqual(wg["caseCount"], 3)
        self.assertEqual(wg["blockId"], 51)

    def _surgeon(self, db, first_name, last_name):
        row = Surgeon(
            first_name=first_name,
            last_name=last_name,
            email=f"{first_name.lower()}.{last_name.lower()}@example.com",
            is_active=True,
            staff_type="physician",
        )
        db.add(row)
        db.flush()
        return row


if __name__ == "__main__":
    unittest.main()
