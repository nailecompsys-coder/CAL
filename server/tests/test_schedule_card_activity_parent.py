import os
import unittest
from datetime import date, time

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("SECRET_KEY", "test-secret")

from sqlalchemy import create_engine, event, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from app.models import (
    AprimaCachedAppointment,
    Base,
    FaxDocument,
    FaxIngestRow,
    FaxIngestRun,
    Location,
    ScheduleCard,
    ScheduleCardActivity,
    ScheduleCardWeek,
    Surgeon,
    SurgicalCase,
)


def _enable_sqlite_foreign_keys(dbapi_connection, _connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


class CardLineParentTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        event.listen(self.engine, "connect", _enable_sqlite_foreign_keys)
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)

    def tearDown(self):
        Base.metadata.drop_all(self.engine)
        self.engine.dispose()

    def test_only_the_card_deletes_a_line(self):
        db = self.Session()
        try:
            surgeon = Surgeon(first_name="Alex", last_name="Smith", email="as@example.com", is_active=True)
            location = Location(name="Minneola OR", abbreviation="MN-OR", location_type="hospital", is_active=True)
            db.add_all([surgeon, location])
            db.commit()
            week = ScheduleCardWeek(surgeon_id=surgeon.id, week_start=date(2026, 9, 14), master_revision="test")
            db.add(week)
            db.commit()
            card = ScheduleCard(
                week_id=week.id,
                surgeon_id=surgeon.id,
                date=date(2026, 9, 14),
                session="am",
                baseline_state="assigned",
                effective_state="assigned",
                baseline_location_id=location.id,
                effective_location_id=location.id,
            )
            db.add(card)
            case = SurgicalCase(
                surgeon_id=surgeon.id,
                date=date(2026, 9, 14),
                start_time=time(7, 30),
                patient_name="Case Patient",
                procedure="Case",
                location_id=location.id,
                status="scheduled",
            )
            fax = FaxDocument(external_fax_id=41, source_label="test")
            db.add_all([card, case, fax])
            db.commit()
            run = FaxIngestRun(fax_document_id=fax.id, engine_version="test", status="staged")
            db.add(run)
            db.commit()
            fax_row = FaxIngestRow(
                run_id=run.id,
                page_number=1,
                surgeon_id=surgeon.id,
                surgeon_initials="AS",
                case_date=date(2026, 9, 14),
                session="am",
                row_type="surgical",
                patient_name="Fax Patient",
                procedure="Case",
                normalized_key="fax-line",
            )
            visit = AprimaCachedAppointment(
                appointment_id="visit-1",
                kind="patient",
                date=date(2026, 9, 14),
                content_hash="hash",
                payload_json="{}",
            )
            db.add_all([fax_row, visit])
            db.commit()
            db.add_all([
                ScheduleCardActivity(
                    schedule_card_id=card.id,
                    surgeon_id=surgeon.id,
                    location_id=location.id,
                    activity_date=card.date,
                    session="am",
                    activity_type="surgical",
                    patient_name="Case Patient",
                    procedure="Case",
                    source_system="old",
                    source_record_key="case",
                    identity_key="case",
                    surgical_case_id=case.id,
                ),
                ScheduleCardActivity(
                    schedule_card_id=card.id,
                    surgeon_id=surgeon.id,
                    location_id=location.id,
                    activity_date=card.date,
                    session="am",
                    activity_type="surgical",
                    patient_name="Fax Patient",
                    procedure="Case",
                    source_system="fax",
                    source_record_key="fax",
                    identity_key="fax",
                    fax_ingest_row_id=fax_row.id,
                ),
                ScheduleCardActivity(
                    schedule_card_id=card.id,
                    surgeon_id=surgeon.id,
                    location_id=location.id,
                    activity_date=card.date,
                    session="am",
                    activity_type="clinic",
                    patient_name="Visit",
                    procedure="Visit",
                    source_system="aprima",
                    source_record_key="visit-1",
                    identity_key="visit-1",
                    aprima_appointment_id=visit.appointment_id,
                ),
            ])
            db.commit()

            db.delete(case)
            db.delete(fax_row)
            db.delete(visit)
            db.commit()
            db.expire_all()

            kept = db.query(ScheduleCardActivity).order_by(ScheduleCardActivity.id).all()
            self.assertEqual(len(kept), 3)
            self.assertEqual([line.surgical_case_id for line in kept], [None, None, None])
            self.assertEqual([line.fax_ingest_row_id for line in kept], [None, None, None])
            self.assertEqual([line.aprima_appointment_id for line in kept], [None, None, None])
            self.assertEqual({line.schedule_card_id for line in kept}, {card.id})

            db.delete(card)
            db.commit()
            self.assertEqual(db.query(ScheduleCardActivity).count(), 0)
        finally:
            db.close()

    def test_line_cannot_name_a_different_half_day_than_its_card(self):
        db = self.Session()
        try:
            surgeon = Surgeon(first_name="Alex", last_name="Smith", email="as2@example.com", is_active=True)
            location = Location(name="Minneola OR", abbreviation="MN-OR", location_type="hospital", is_active=True)
            db.add_all([surgeon, location])
            db.commit()
            week = ScheduleCardWeek(surgeon_id=surgeon.id, week_start=date(2026, 10, 19), master_revision="test")
            db.add(week)
            db.commit()
            card = ScheduleCard(
                week_id=week.id,
                surgeon_id=surgeon.id,
                date=date(2026, 10, 19),
                session="am",
                baseline_state="na",
                effective_state="na",
            )
            db.add(card)
            db.commit()
            db.add(ScheduleCardActivity(
                schedule_card_id=card.id,
                surgeon_id=surgeon.id,
                activity_date=card.date,
                session="pm",
                activity_type="surgical",
                patient_name="Moved",
                procedure="Case",
                source_system="fax",
                source_record_key="wrong-session",
                identity_key="wrong-session",
            ))
            with self.assertRaises(IntegrityError):
                db.commit()
        finally:
            db.close()

    def test_card_line_schema_names_one_deleting_parent(self):
        with self.engine.connect() as conn:
            ddl = conn.execute(text(
                "SELECT sql FROM sqlite_master WHERE name = 'schedule_card_activities'"
            )).scalar()
        self.assertIn("REFERENCES schedule_cards", ddl)
        self.assertIn("fk_schedule_card_activities_card_identity", ddl)
        self.assertEqual(ddl.upper().count("ON DELETE SET NULL"), 3)


if __name__ == "__main__":
    unittest.main()
