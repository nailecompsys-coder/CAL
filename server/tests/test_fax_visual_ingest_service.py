import os
import unittest
from datetime import date, time

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("SECRET_KEY", "test-secret")

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.fax_visual_ingest_service import (
    BackupReceipt,
    FaxVisualRow,
    apply_visual_schedule,
    duplicate_first_analysis,
)
from app.models import (
    AdminNotification,
    Base,
    ClinicSchedule,
    CoSurgeonPair,
    Location,
    NativeScheduleAlert,
    ORBlockAssignment,
    ORBlockInstance,
    ScheduleChangeEvent,
    Surgeon,
    SurgicalCase,
)


class FaxVisualIngestServiceTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)
        self.db = self.Session()
        self.jf = Surgeon(first_name="Jorge", last_name="Florin", email="jf@example.com", is_active=True)
        self.jb = Surgeon(first_name="Jason", last_name="Boardman", email="jb@example.com", is_active=True)
        self.ln = Surgeon(first_name="Lars", last_name="Nelson", email="ln@example.com", is_active=True)
        self.mn = Location(name="Minneola OR", abbreviation="MN-OR", location_type="hospital", is_active=True)
        self.al = Location(name="Altamonte OR", abbreviation="AL-OR", location_type="hospital", is_active=True)
        self.ap = Location(name="Apopka OR", abbreviation="AP-OR", location_type="hospital", is_active=True)
        self.cl = Location(name="HP Clermont Clinic", abbreviation="CL-OV", location_type="clinic", is_active=True)
        self.db.add_all([self.jf, self.jb, self.ln, self.mn, self.al, self.ap, self.cl])
        self.db.commit()
        self._block(self.jf, self.mn, date(2026, 9, 16), time(7, 0), time(12, 0))
        self._block(self.ln, self.al, date(2026, 9, 17), time(7, 0), time(12, 0))

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def _block(self, surgeon, loc, day, start, end):
        block = ORBlockInstance(
            location_id=loc.id,
            date=day,
            session="am",
            start_time=start,
            end_time=end,
            status="assigned",
        )
        self.db.add(block)
        self.db.flush()
        self.db.add(ORBlockAssignment(block_instance_id=block.id, surgeon_id=surgeon.id, start_time=start, case_count=1))
        self.db.commit()
        return block

    def row(self, **kw):
        defaults = dict(
            fax_id=162,
            page=1,
            surgeon_initials="JF",
            surgeon_name="Jorge Florin",
            case_date=date(2026, 9, 16),
            start_time=time(7, 15),
            row_type="surgical",
            room="MIN S05",
            patient_name="White, Jeffrey Allan",
            procedure="Robotic assisted case",
        )
        defaults.update(kw)
        return FaxVisualRow(**defaults)

    def test_write_requires_backup_receipt(self):
        with self.assertRaisesRegex(ValueError, "backup"):
            apply_visual_schedule(
                self.db,
                [self.row()],
                backup=BackupReceipt(False, "failed"),
                source_fax_id=162,
            )
        self.assertEqual(self.db.query(SurgicalCase).count(), 0)

    def test_visual_sot_updates_same_patient_date_and_stays_quiet(self):
        existing = SurgicalCase(
            surgeon_id=self.jb.id,
            date=date(2026, 9, 16),
            start_time=time(9, 15),
            patient_name="White, Jeffrey Allan",
            procedure="Old",
            location_id=self.mn.id,
            room_text="MIN S05",
            status="scheduled",
        )
        self.db.add(existing)
        self.db.commit()

        result = apply_visual_schedule(
            self.db,
            [self.row()],
            backup=BackupReceipt(True, "unit-test", "/tmp/backup.dump"),
            source_fax_id=162,
        )

        self.assertEqual(result["surgical_updated"], 1)
        self.assertEqual(self.db.query(SurgicalCase).count(), 1)
        case = self.db.query(SurgicalCase).one()
        self.assertEqual(case.surgeon_id, self.jf.id)
        self.assertEqual(case.start_time, time(7, 15))
        self.assertEqual(case.or_block_instance_id, 1)
        self.assertIn("Fax 162", case.notes)
        self.assertEqual(self.db.query(AdminNotification).count(), 0)
        self.assertEqual(self.db.query(NativeScheduleAlert).count(), 0)
        self.assertEqual(self.db.query(ScheduleChangeEvent).count(), 1)

    def test_shared_assist_rows_collapse_to_one_case(self):
        self.db.add(CoSurgeonPair(primary_surgeon_id=self.jf.id, assisting_surgeon_id=self.jb.id, is_active=True))
        self.db.commit()
        rows = [
            self.row(surgeon_initials="JF"),
            self.row(surgeon_initials="JB"),
        ]
        result = apply_visual_schedule(
            self.db,
            rows,
            backup=BackupReceipt(True, "unit-test", "/tmp/backup.dump"),
            source_fax_id=162,
        )
        self.assertEqual(result["surgical_created"], 1)
        self.assertEqual(result["assist_cases"], 1)
        case = self.db.query(SurgicalCase).one()
        self.assertEqual(case.surgeon_id, self.jf.id)
        self.assertEqual(case.assisting_surgeon_id, self.jb.id)

    def test_surgical_row_without_matching_block_is_parked(self):
        result = apply_visual_schedule(
            self.db,
            [self.row(room="APK S03")],
            backup=BackupReceipt(True, "unit-test", "/tmp/backup.dump"),
            source_fax_id=162,
        )
        self.assertEqual(result["surgical_created"], 0)
        self.assertEqual(result["surgical_skipped"], 1)
        self.assertEqual(self.db.query(SurgicalCase).count(), 0)
        self.assertIn("no matching static OR block", result["redflags"][0])

    def test_duplicate_first_flags_exact_shared_rows(self):
        rows = [self.row(surgeon_initials="JF"), self.row(surgeon_initials="JB")]
        analysis = duplicate_first_analysis(rows)
        self.assertEqual(analysis["fax_surgical_rows"], 2)
        self.assertEqual(len(analysis["fax_same_patient_date_groups"]), 1)
        self.assertEqual(len(analysis["fax_exact_duplicate_groups"]), 1)

    def test_clinic_rows_update_one_card(self):
        self.db.add(ClinicSchedule(
            surgeon_id=self.jb.id,
            date=date(2026, 9, 16),
            session="am",
            location_id=self.cl.id,
            assignment_type="assigned",
        ))
        self.db.commit()
        rows = [
            self.row(
                surgeon_initials="JB",
                case_date=date(2026, 9, 16),
                start_time=time(8, 30),
                row_type="clinic",
                room="CLMMFLGS",
                patient_name="Flores, Anna",
                procedure="Visit",
            ),
            self.row(
                surgeon_initials="JB",
                case_date=date(2026, 9, 16),
                start_time=time(8, 40),
                row_type="clinic",
                room="CLMMFLGS",
                patient_name="Damon, Brandy",
                procedure="Visit",
            ),
        ]
        result = apply_visual_schedule(
            self.db,
            rows,
            backup=BackupReceipt(True, "unit-test", "/tmp/backup.dump"),
            source_fax_id=162,
        )
        self.assertEqual(result["clinic_created"], 0)
        self.assertEqual(result["clinic_updated"], 1)
        self.assertEqual(self.db.query(ClinicSchedule).count(), 1)
        card = self.db.query(ClinicSchedule).one()
        self.assertIn("08:30 Flores", card.notes)
        self.assertIn("08:40 Damon", card.notes)

    def test_clinic_rows_without_master_card_are_parked(self):
        rows = [
            self.row(
                surgeon_initials="JB",
                case_date=date(2026, 9, 16),
                start_time=time(8, 30),
                row_type="clinic",
                room="CLMMFLGS",
                patient_name="Flores, Anna",
                procedure="Visit",
            ),
        ]
        result = apply_visual_schedule(
            self.db,
            rows,
            backup=BackupReceipt(True, "unit-test", "/tmp/backup.dump"),
            source_fax_id=162,
        )
        self.assertEqual(result["clinic_created"], 0)
        self.assertEqual(result["clinic_updated"], 0)
        self.assertEqual(result["clinic_skipped_rows"], 1)
        self.assertEqual(self.db.query(ClinicSchedule).count(), 0)
        self.assertIn("no existing CAL card", result["redflags"][0])


if __name__ == "__main__":
    unittest.main()
