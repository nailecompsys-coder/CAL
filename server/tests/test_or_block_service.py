import os
import unittest
from datetime import date, time, timedelta
from unittest.mock import patch

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("SECRET_KEY", "test-secret")

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models import (
    Base,
    ClinicSchedule,
    DayOff,
    Location,
    ORBlockAuditEvent,
    ORBlockAssignment,
    ORBlockInstance,
    ScheduleChangeEvent,
    Surgeon,
    SurgicalCase,
)
from app.or_block_service import (
    BlockORCreateInput,
    assign_block,
    block_assignment_warnings,
    clear_block_assignment,
    copy_or_block_capacity,
    create_or_blocks,
    delete_or_block_instance,
    remove_block_assignment,
    scheduler_native_home,
    update_block_assignment,
    update_or_block_instance,
)


class ORBlockServiceTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(bind=self.engine)
        self.Session = sessionmaker(bind=self.engine)

    def tearDown(self):
        Base.metadata.drop_all(bind=self.engine)
        self.engine.dispose()

    def test_multi_location_block_creates_one_instance_per_location_day(self):
        db = self.Session()
        try:
            first = self._location(db, "Advent Winter Garden", "WG")
            second = self._location(db, "Advent Altamonte", "AL")
            monday = date(2026, 7, 6)

            result = create_or_blocks(db, BlockORCreateInput(
                name="Open AM Block",
                start_date=monday,
                end_date=monday + timedelta(days=1),
                weekdays=[0, 1],
                location_ids=[first.id, second.id],
                session="am",
                start_time=time(7, 0),
                end_time=time(12, 0),
            ), admin_id=None)

            self.assertEqual(result["created"], 4)
            blocks = db.query(ORBlockInstance).order_by(ORBlockInstance.date, ORBlockInstance.location_id).all()
            self.assertEqual(len(blocks), 4)
            self.assertEqual({row.location_id for row in blocks}, {first.id, second.id})
            self.assertTrue(all(row.assigned_surgeon_id is None for row in blocks))
            self.assertEqual(db.query(ORBlockAuditEvent).filter(ORBlockAuditEvent.event_type == "created").count(), 4)
        finally:
            db.close()

    def test_duplicate_block_time_for_same_location_and_date_is_rejected(self):
        db = self.Session()
        try:
            hospital = self._location(db, "Advent Winter Garden", "WG")
            monday = date(2026, 7, 6)
            payload = BlockORCreateInput(
                name="Open AM Block",
                start_date=monday,
                end_date=monday,
                weekdays=[monday.weekday()],
                location_ids=[hospital.id],
                session="am",
                start_time=time(7, 0),
                end_time=time(12, 0),
                recurrence="once",
                room_text="S03",
            )
            create_or_blocks(db, payload)

            with self.assertRaises(ValueError) as ctx:
                create_or_blocks(db, payload)

            self.assertIn("Duplicate Block OR time", str(ctx.exception))
            self.assertEqual(db.query(ORBlockInstance).count(), 1)
        finally:
            db.close()

    def test_dual_rooms_same_hospital_day_time_are_allowed(self):
        db = self.Session()
        try:
            hospital = self._location(db, "Advent Winter Garden", "WG-OR")
            monday = date(2026, 8, 3)
            base = dict(
                start_date=monday,
                end_date=monday,
                weekdays=[monday.weekday()],
                location_ids=[hospital.id],
                session="am",
                start_time=time(7, 0),
                end_time=time(12, 0),
                recurrence="once",
            )
            create_or_blocks(db, BlockORCreateInput(name="Dr A room", room_text="S03", **base))
            create_or_blocks(db, BlockORCreateInput(name="Dr B room", room_text="S08", **base))
            rows = db.query(ORBlockInstance).order_by(ORBlockInstance.room_text).all()
            self.assertEqual(len(rows), 2)
            self.assertEqual({row.room_text for row in rows}, {"S03", "S08"})
        finally:
            db.close()

    def test_copy_capacity_forward_skips_conflicts(self):
        db = self.Session()
        try:
            hospital = self._location(db, "Advent Winter Garden", "WG-OR")
            monday = date(2026, 8, 3)
            create_or_blocks(db, BlockORCreateInput(
                name="WG Mon",
                start_date=monday,
                end_date=monday,
                weekdays=[0],
                location_ids=[hospital.id],
                session="am",
                start_time=time(7, 0),
                end_time=time(12, 0),
                recurrence="once",
                room_text="S03",
            ))
            # Pre-seed next Monday conflict
            next_mon = monday + timedelta(days=7)
            create_or_blocks(db, BlockORCreateInput(
                name="Existing",
                start_date=next_mon,
                end_date=next_mon,
                weekdays=[0],
                location_ids=[hospital.id],
                session="am",
                start_time=time(7, 0),
                end_time=time(12, 0),
                recurrence="once",
                room_text="S03",
            ))
            result = copy_or_block_capacity(
                db,
                source_week_start=monday,
                weekdays=[0],
                end_date=monday + timedelta(days=21),
                location_id=hospital.id,
            )
            self.assertEqual(result["created"], 2)  # +14 and +21; +7 skipped
            self.assertTrue(any("Skipped" in note for note in result["skipped"]))
            self.assertEqual(db.query(ORBlockInstance).count(), 4)
        finally:
            db.close()

    def test_update_block_changes_times_and_facility(self):
        db = self.Session()
        try:
            first = self._location(db, "Advent Winter Garden", "WG")
            second = self._location(db, "Advent Altamonte", "AL")
            monday = date(2026, 7, 6)
            block_id = create_or_blocks(db, BlockORCreateInput(
                name="Open AM Block",
                start_date=monday,
                end_date=monday,
                weekdays=[monday.weekday()],
                location_ids=[first.id],
                session="am",
                start_time=time(7, 0),
                end_time=time(12, 0),
                recurrence="once",
            ))["instance_ids"][0]

            updated = update_or_block_instance(
                db,
                block_id,
                location_id=second.id,
                session="pm",
                start_time=time(12, 0),
                end_time=time(17, 0),
                notes="Moved PM",
            )

            self.assertEqual(updated.location_id, second.id)
            self.assertEqual(updated.session, "pm")
            self.assertEqual(updated.start_time, time(12, 0))
            self.assertEqual(updated.end_time, time(17, 0))
            self.assertEqual(updated.notes, "Moved PM")
            self.assertEqual(
                db.query(ORBlockAuditEvent).filter(ORBlockAuditEvent.event_type == "updated").count(),
                1,
            )
        finally:
            db.close()

    def test_delete_open_block_removes_instance(self):
        db = self.Session()
        try:
            hospital = self._location(db, "Advent Winter Garden", "WG")
            monday = date(2026, 7, 6)
            block_id = create_or_blocks(db, BlockORCreateInput(
                name="Open AM Block",
                start_date=monday,
                end_date=monday,
                weekdays=[monday.weekday()],
                location_ids=[hospital.id],
                session="am",
                start_time=time(7, 0),
                end_time=time(12, 0),
                recurrence="once",
            ))["instance_ids"][0]

            delete_or_block_instance(db, block_id)
            self.assertEqual(db.query(ORBlockInstance).count(), 0)
            self.assertEqual(
                db.query(ORBlockAuditEvent).filter(ORBlockAuditEvent.block_instance_id == block_id).count(),
                0,
            )
            self.assertEqual(
                db.query(ScheduleChangeEvent).filter(ScheduleChangeEvent.event_type == "or_block_deleted").count(),
                1,
            )
        finally:
            db.close()

    def test_delete_open_block_clears_prior_audit_rows(self):
        db = self.Session()
        try:
            hospital = self._location(db, "Advent Winter Garden", "WG")
            monday = date(2026, 7, 6)
            block_id = create_or_blocks(db, BlockORCreateInput(
                name="Open AM Block",
                start_date=monday,
                end_date=monday,
                weekdays=[monday.weekday()],
                location_ids=[hospital.id],
                session="am",
                start_time=time(7, 0),
                end_time=time(12, 0),
                recurrence="once",
            ))["instance_ids"][0]
            # create_or_blocks writes audit rows that previously blocked DELETE
            self.assertGreater(
                db.query(ORBlockAuditEvent).filter(ORBlockAuditEvent.block_instance_id == block_id).count(),
                0,
            )
            delete_or_block_instance(db, block_id, admin_id=None)
            self.assertEqual(db.query(ORBlockInstance).filter(ORBlockInstance.id == block_id).count(), 0)
            self.assertEqual(
                db.query(ORBlockAuditEvent).filter(ORBlockAuditEvent.block_instance_id == block_id).count(),
                0,
            )
        finally:
            db.close()

    def test_delete_assigned_block_is_rejected(self):
        db = self.Session()
        try:
            surgeon = self._surgeon(db, "Chris", "Johnson")
            hospital = self._location(db, "Advent Winter Garden", "WG")
            monday = date(2026, 7, 6)
            block_id = create_or_blocks(db, BlockORCreateInput(
                name="Open AM Block",
                start_date=monday,
                end_date=monday,
                weekdays=[monday.weekday()],
                location_ids=[hospital.id],
                session="am",
                start_time=time(7, 0),
                end_time=time(12, 0),
                recurrence="once",
            ))["instance_ids"][0]
            assign_block(db, block_id, surgeon.id, assigned_start_time=time(7, 30), case_count=1)

            with self.assertRaises(ValueError) as ctx:
                delete_or_block_instance(db, block_id)
            self.assertIn("assignment", str(ctx.exception).lower())
            self.assertEqual(db.query(ORBlockInstance).count(), 1)
        finally:
            db.close()

    def test_overlapping_block_time_for_same_location_is_rejected(self):
        db = self.Session()
        try:
            hospital = self._location(db, "Advent Winter Garden", "WG")
            monday = date(2026, 7, 6)
            create_or_blocks(db, BlockORCreateInput(
                name="Open AM Block",
                start_date=monday,
                end_date=monday,
                weekdays=[monday.weekday()],
                location_ids=[hospital.id],
                session="am",
                start_time=time(7, 0),
                end_time=time(12, 0),
                recurrence="once",
            ))

            with self.assertRaises(ValueError):
                create_or_blocks(db, BlockORCreateInput(
                    name="Competing Block",
                    start_date=monday,
                    end_date=monday,
                    weekdays=[monday.weekday()],
                    location_ids=[hospital.id],
                    session="custom",
                    start_time=time(8, 0),
                    end_time=time(11, 0),
                    recurrence="once",
                ))
        finally:
            db.close()

    def test_assignment_warnings_include_clinic_day_off_and_existing_case(self):
        db = self.Session()
        try:
            surgeon = self._surgeon(db, "Chris", "Johnson")
            hospital = self._location(db, "Advent Winter Garden", "WG")
            clinic = self._location(db, "Winter Garden Clinic", "WGC", "clinic")
            # Must be today-forward — rules engine clips past windows to empty.
            block_day = date.today() + timedelta(days=21)
            while block_day.weekday() != 2:  # Wednesday
                block_day += timedelta(days=1)
            block_id = create_or_blocks(db, BlockORCreateInput(
                name="Open AM Block",
                start_date=block_day,
                end_date=block_day,
                weekdays=[block_day.weekday()],
                location_ids=[hospital.id],
                session="am",
                start_time=time(7, 0),
                end_time=time(12, 0),
                recurrence="once",
            ))["instance_ids"][0]
            db.add_all([
                ClinicSchedule(surgeon_id=surgeon.id, location_id=clinic.id, date=block_day, session="am"),
                DayOff(surgeon_id=surgeon.id, start_date=block_day, end_date=block_day, status="approved"),
                SurgicalCase(
                    surgeon_id=surgeon.id,
                    date=block_day,
                    start_time=time(8, 0),
                    end_time=time(9, 0),
                    patient_name="Hidden Patient",
                    procedure="Hidden procedure",
                    location_id=hospital.id,
                ),
            ])
            db.commit()

            block = db.get(ORBlockInstance, block_id)
            warnings = block_assignment_warnings(db, block, surgeon.id)

            self.assertTrue(any("Overlaps clinic schedule" in row for row in warnings))
            self.assertTrue(any("Overlaps day off" in row for row in warnings))
            self.assertTrue(any("Overlaps another surgical case" in row for row in warnings))
            self.assertNotIn("Hidden Patient", " ".join(warnings))
        finally:
            db.close()

    def test_assign_sets_simple_cal_slot_and_event(self):
        db = self.Session()
        try:
            surgeon = self._surgeon(db, "Lucy", "Woodley")
            first = self._location(db, "Advent Winter Garden", "WG")
            second = self._location(db, "Advent Altamonte", "AL")
            block_day = date(2026, 7, 9)
            result = create_or_blocks(db, BlockORCreateInput(
                name="Open PM Block",
                start_date=block_day,
                end_date=block_day,
                weekdays=[block_day.weekday()],
                location_ids=[first.id, second.id],
                session="pm",
                start_time=time(12, 0),
                end_time=time(17, 0),
                recurrence="once",
            ))
            with patch("app.or_block_service.send_push_to_surgeon") as push:
                assigned, _ = assign_block(
                    db,
                    result["instance_ids"][0],
                    surgeon.id,
                    assigned_start_time=time(13, 0),
                    case_count=3,
                    assignment_note="Epic case stack",
                )

            self.assertEqual(assigned.status, "assigned")
            self.assertEqual(assigned.assigned_surgeon_id, surgeon.id)
            self.assertEqual(assigned.assigned_start_time, time(13, 0))
            self.assertEqual(assigned.assigned_case_count, 3)
            self.assertEqual(assigned.assignment_note, "Epic case stack")
            statuses = {row.id: row.status for row in db.query(ORBlockInstance).all()}
            self.assertEqual(statuses[result["instance_ids"][0]], "assigned")
            self.assertEqual(statuses[result["instance_ids"][1]], "open")
            self.assertEqual(db.query(ScheduleChangeEvent).filter(ScheduleChangeEvent.event_type == "block_or_assigned").count(), 1)
            push.assert_called_once()
            args, kwargs = push.call_args
            self.assertEqual(args[0], surgeon.id)
            self.assertEqual(args[1], "Block OR updated")
            self.assertIn("WG", args[2])
            self.assertEqual((kwargs.get("data") or {}).get("kind"), "block_or")
        finally:
            db.close()

    def test_clear_notifies_all_assigned_surgeons(self):
        db = self.Session()
        try:
            chris = self._surgeon(db, "Chris", "Johnson")
            jorge = self._surgeon(db, "Jorge", "Florin")
            hospital = self._location(db, "Advent Winter Garden", "WG")
            block_day = date(2026, 7, 8)
            block_id = create_or_blocks(db, BlockORCreateInput(
                name="Open AM Block",
                start_date=block_day,
                end_date=block_day,
                weekdays=[block_day.weekday()],
                location_ids=[hospital.id],
                session="am",
                start_time=time(7, 0),
                end_time=time(12, 0),
                recurrence="once",
            ))["instance_ids"][0]
            with patch("app.or_block_service.send_push_to_surgeon"):
                assign_block(db, block_id, chris.id, assigned_start_time=time(7, 0), case_count=1)
                assign_block(db, block_id, jorge.id, assigned_start_time=time(10, 0), case_count=2)
            with patch("app.or_block_service.send_push_to_surgeon") as push:
                clear_block_assignment(db, block_id)
            notified = {call.args[0] for call in push.call_args_list}
            self.assertEqual(notified, {chris.id, jorge.id})
            self.assertTrue(all(call.args[1] == "Block OR removed" for call in push.call_args_list))
        finally:
            db.close()

    def test_block_serializes_multiple_assignments_in_time_order(self):
        db = self.Session()
        try:
            chris = self._surgeon(db, "Chris", "Johnson")
            jorge = self._surgeon(db, "Jorge", "Florin")
            hospital = self._location(db, "Advent Winter Garden", "WG")
            block_day = date(2026, 7, 8)
            block_id = create_or_blocks(db, BlockORCreateInput(
                name="Open AM Block",
                start_date=block_day,
                end_date=block_day,
                weekdays=[block_day.weekday()],
                location_ids=[hospital.id],
                session="am",
                start_time=time(7, 0),
                end_time=time(12, 0),
                recurrence="once",
            ))["instance_ids"][0]
            assign_block(db, block_id, chris.id, assigned_start_time=time(9, 0), case_count=1)
            assign_block(db, block_id, chris.id, assigned_start_time=time(7, 0), case_count=1)
            assign_block(db, block_id, jorge.id, assigned_start_time=time(10, 0), case_count=2)

            payload = scheduler_native_home(db, block_day, block_day)
            assignments = payload["blocks"][0]["assignments"]

            self.assertEqual([row["label"] for row in assignments], [
                "WG - 07:00 - 1 Case CJ",
                "WG - 09:00 - 1 Case CJ",
                "WG - 10:00 - 2 Cases JF",
            ])
            self.assertEqual(payload["blocks"][0]["caseCount"], 4)
        finally:
            db.close()

    def test_existing_same_location_block_does_not_make_surgeon_unavailable(self):
        db = self.Session()
        try:
            surgeon = self._surgeon(db, "Chris", "Johnson")
            winter_garden = self._location(db, "Advent Winter Garden", "WG")
            altamonte = self._location(db, "Advent Altamonte", "AL")
            block_day = date(2026, 7, 8)
            assigned = ORBlockInstance(
                location_id=winter_garden.id,
                date=block_day,
                session="am",
                start_time=time(7, 0),
                end_time=time(12, 0),
                status="assigned",
                assigned_surgeon_id=surgeon.id,
                assigned_start_time=time(7, 0),
                assigned_case_count=1,
            )
            same_facility = ORBlockInstance(
                location_id=winter_garden.id,
                date=block_day,
                session="am",
                start_time=time(7, 0),
                end_time=time(12, 0),
                status="open",
            )
            different_facility = ORBlockInstance(
                location_id=altamonte.id,
                date=block_day,
                session="am",
                start_time=time(7, 0),
                end_time=time(12, 0),
                status="open",
            )
            db.add_all([assigned, same_facility, different_facility])
            db.commit()

            same_warnings = block_assignment_warnings(db, same_facility, surgeon.id)
            different_warnings = block_assignment_warnings(db, different_facility, surgeon.id)

            self.assertFalse(any("Already assigned Block OR" in row for row in same_warnings))
            self.assertTrue(any("Already assigned Block OR: WG" in row for row in different_warnings))
        finally:
            db.close()

    def test_clear_assignment_returns_block_to_open(self):
        db = self.Session()
        try:
            surgeon = self._surgeon(db, "Chris", "Johnson")
            hospital = self._location(db, "Advent Winter Garden", "WG")
            block_day = date(2026, 7, 9)
            block_id = create_or_blocks(db, BlockORCreateInput(
                name="Open AM Block",
                start_date=block_day,
                end_date=block_day,
                weekdays=[block_day.weekday()],
                location_ids=[hospital.id],
                session="am",
                start_time=time(7, 0),
                end_time=time(12, 0),
                recurrence="once",
            ))["instance_ids"][0]
            assign_block(db, block_id, surgeon.id, assigned_start_time=time(7, 30), case_count=2, assignment_note="hold")

            cleared = clear_block_assignment(db, block_id)

            self.assertEqual(cleared.status, "open")
            self.assertIsNone(cleared.assigned_surgeon_id)
            self.assertIsNone(cleared.assigned_start_time)
            self.assertIsNone(cleared.assigned_case_count)
            self.assertIsNone(cleared.assignment_note)
            self.assertEqual(db.query(ScheduleChangeEvent).filter(ScheduleChangeEvent.event_type == "block_or_assignment_cleared").count(), 1)
        finally:
            db.close()

    def test_remove_single_block_assignment_keeps_others(self):
        db = self.Session()
        try:
            chris = self._surgeon(db, "Chris", "Johnson")
            jorge = self._surgeon(db, "Jorge", "Florin")
            hospital = self._location(db, "Advent Winter Garden", "WG")
            block_day = date(2026, 7, 9)
            block_id = create_or_blocks(db, BlockORCreateInput(
                name="Open AM Block",
                start_date=block_day,
                end_date=block_day,
                weekdays=[block_day.weekday()],
                location_ids=[hospital.id],
                session="am",
                start_time=time(7, 0),
                end_time=time(12, 0),
                recurrence="once",
            ))["instance_ids"][0]
            assign_block(db, block_id, chris.id, assigned_start_time=time(7, 0), case_count=1)
            assign_block(db, block_id, jorge.id, assigned_start_time=time(8, 0), case_count=1)
            block = db.get(ORBlockInstance, block_id)
            chris_assignment = next(row for row in block.assignments if row.surgeon_id == chris.id)

            updated = remove_block_assignment(db, block_id, chris_assignment.id)

            self.assertEqual(updated.status, "assigned")
            self.assertEqual(len(updated.assignments), 1)
            self.assertEqual(updated.assignments[0].surgeon_id, jorge.id)
            self.assertEqual(updated.assigned_surgeon_id, jorge.id)
            self.assertEqual(updated.assigned_start_time, time(8, 0))
            self.assertEqual(
                db.query(ScheduleChangeEvent).filter(ScheduleChangeEvent.event_type == "block_or_assignment_removed").count(),
                1,
            )
        finally:
            db.close()

    def test_update_block_assignment_changes_surgeon_in_place(self):
        db = self.Session()
        try:
            alex = self._surgeon(db, "Alex", "Beceiro")
            jorge = self._surgeon(db, "Jorge", "Florin")
            hospital = self._location(db, "Advent Winter Garden", "WG")
            block_day = date(2026, 7, 9)
            block_id = create_or_blocks(db, BlockORCreateInput(
                name="Open AM Block",
                start_date=block_day,
                end_date=block_day,
                weekdays=[block_day.weekday()],
                location_ids=[hospital.id],
                session="am",
                start_time=time(7, 0),
                end_time=time(12, 0),
                recurrence="once",
            ))["instance_ids"][0]
            assign_block(db, block_id, alex.id, assigned_start_time=time(9, 0), case_count=1)
            block = db.get(ORBlockInstance, block_id)
            assignment_id = block.assignments[0].id

            updated, _ = update_block_assignment(
                db,
                block_id,
                assignment_id,
                jorge.id,
                assigned_start_time=time(9, 0),
                case_count=1,
            )

            self.assertEqual(len(updated.assignments), 1)
            self.assertEqual(updated.assignments[0].surgeon_id, jorge.id)
            self.assertEqual(updated.assignments[0].start_time, time(9, 0))
            self.assertEqual(updated.assigned_surgeon_id, jorge.id)
        finally:
            db.close()

    def test_assign_block_rejects_duplicate_surgeon_start(self):
        db = self.Session()
        try:
            jorge = self._surgeon(db, "Jorge", "Florin")
            hospital = self._location(db, "Advent Winter Garden", "WG")
            block_day = date(2026, 7, 9)
            block_id = create_or_blocks(db, BlockORCreateInput(
                name="Open AM Block",
                start_date=block_day,
                end_date=block_day,
                weekdays=[block_day.weekday()],
                location_ids=[hospital.id],
                session="am",
                start_time=time(7, 0),
                end_time=time(12, 0),
                recurrence="once",
            ))["instance_ids"][0]
            assign_block(db, block_id, jorge.id, assigned_start_time=time(10, 0), case_count=1)
            with self.assertRaises(ValueError):
                assign_block(db, block_id, jorge.id, assigned_start_time=time(10, 0), case_count=1)
        finally:
            db.close()

    def test_scheduler_native_home_excludes_phi(self):
        db = self.Session()
        try:
            surgeon = self._surgeon(db, "Jorge", "Florin")
            hospital = self._location(db, "Advent Lake Mary", "LM")
            block_day = date(2026, 7, 10)
            block_id = create_or_blocks(db, BlockORCreateInput(
                name="Open AM Block",
                start_date=block_day,
                end_date=block_day,
                weekdays=[block_day.weekday()],
                location_ids=[hospital.id],
                session="am",
                start_time=time(7, 0),
                end_time=time(12, 0),
                recurrence="once",
            ))["instance_ids"][0]
            assign_block(db, block_id, surgeon.id)
            db.add(SurgicalCase(
                surgeon_id=surgeon.id,
                or_block_instance_id=block_id,
                date=block_day,
                start_time=time(7, 30),
                end_time=time(8, 30),
                patient_name="Do Not Show",
                patient_dob="1/1/1960",
                patient_phone="4075550100",
                procedure="Private procedure",
                location_id=hospital.id,
            ))
            db.commit()

            payload = scheduler_native_home(db, block_day, block_day)
            serialized = str(payload)

            self.assertIn("blocks", payload)
            self.assertEqual(payload["blocks"][0]["assignmentLabel"], "LM - 07:00 - 1 Case JF")
            self.assertNotIn("Do Not Show", serialized)
            self.assertNotIn("patient_dob", serialized)
            self.assertNotIn("patient_phone", serialized)
            self.assertNotIn("Private procedure", serialized)
        finally:
            db.close()

    def test_assign_with_warnings_requires_override_note(self):
        db = self.Session()
        try:
            surgeon = self._surgeon(db, "Chris", "Johnson")
            winter_garden = self._location(db, "Advent Winter Garden", "WG")
            altamonte = self._location(db, "Advent Altamonte", "AL")
            block_day = date.today() + timedelta(days=21)
            while block_day.weekday() != 2:
                block_day += timedelta(days=1)
            existing = ORBlockInstance(
                location_id=winter_garden.id,
                date=block_day,
                session="am",
                start_time=time(7, 0),
                end_time=time(12, 0),
                status="assigned",
                assigned_surgeon_id=surgeon.id,
                assigned_start_time=time(7, 0),
                assigned_case_count=1,
            )
            open_block = ORBlockInstance(
                location_id=altamonte.id,
                date=block_day,
                session="am",
                start_time=time(7, 0),
                end_time=time(12, 0),
                status="open",
            )
            db.add_all([existing, open_block])
            db.commit()

            with self.assertRaises(ValueError) as ctx:
                assign_block(db, open_block.id, surgeon.id)
            self.assertIn("Add a note to override", str(ctx.exception))

            assigned, warnings = assign_block(
                db,
                open_block.id,
                surgeon.id,
                assignment_note="Spoke with Chris — OK to double",
            )
            self.assertEqual(assigned.status, "assigned")
            self.assertTrue(any("Already assigned Block OR" in row for row in warnings))
            self.assertEqual(assigned.assignment_note, "Spoke with Chris — OK to double")
        finally:
            db.close()

    def _surgeon(self, db, first_name, last_name):
        row = Surgeon(
            first_name=first_name,
            last_name=last_name,
            email=f"{first_name.lower()}.{last_name.lower()}@example.com",
            staff_type="physician",
            is_active=True,
        )
        db.add(row)
        db.flush()
        return row

    def _location(self, db, name, abbreviation, location_type="hospital"):
        row = Location(name=name, abbreviation=abbreviation, location_type=location_type, is_active=True)
        db.add(row)
        db.flush()
        return row


if __name__ == "__main__":
    unittest.main()
