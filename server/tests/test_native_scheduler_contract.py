import os
import unittest
from datetime import date, time
from unittest.mock import patch

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("SECRET_KEY", "test-secret")

from jose import jwt
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.auth_tokens import ALGORITHM, SECRET_KEY
from app.models import AdminUser, Base, Location, Surgeon, SurgicalCase
from app.or_block_service import BlockORCreateInput, assign_block, create_or_blocks
from app.routers.native_scheduler_api import (
    SchedulerCaseBody,
    SchedulerCreateBlockBody,
    SchedulerOtpRequestBody,
    SchedulerOtpVerifyBody,
    SchedulerUpdateBlockBody,
    scheduler_add_block_case,
    scheduler_clear_block_assignment,
    scheduler_create_block,
    scheduler_delete_block,
    scheduler_home,
    scheduler_meta,
    scheduler_otp_request,
    scheduler_otp_verify,
    scheduler_update_block,
)
from fastapi import HTTPException


class NativeSchedulerContractTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(bind=self.engine)
        self.Session = sessionmaker(bind=self.engine)

    def tearDown(self):
        Base.metadata.drop_all(bind=self.engine)
        self.engine.dispose()

    def test_scheduler_otp_issues_scheduler_scoped_token(self):
        db = self.Session()
        try:
            admin = AdminUser(
                username="scheduler",
                email="scheduler@example.com",
                phone="4075550100",
                password_hash="x",
                role="scheduler",
                is_active=True,
            )
            db.add(admin)
            db.commit()

            with patch("app.routers.native_scheduler_api.generate_sms_otp", return_value=(True, "123456", None)), patch(
                "app.routers.native_scheduler_api.send_email",
                return_value=True,
            ):
                response = scheduler_otp_request(SchedulerOtpRequestBody(email="scheduler@example.com"), db=db)

            self.assertTrue(response["ok"])
            verified = scheduler_otp_verify(SchedulerOtpVerifyBody(email="scheduler@example.com", code="123456"), db=db)
            payload = jwt.decode(verified["token"], SECRET_KEY, algorithms=[ALGORITHM])

            self.assertEqual(payload["type"], "native_scheduler")
            self.assertEqual(payload["mobile_scope"], "scheduler")
            self.assertEqual(verified["identity"]["role"], "scheduler")
        finally:
            db.close()

    def test_scheduler_home_contract_has_blocks_and_no_phi(self):
        db = self.Session()
        try:
            admin = AdminUser(username="admin", email="admin@example.com", password_hash="x", role="admin", is_active=True)
            surgeon = Surgeon(first_name="Chris", last_name="Johnson", email="chris@example.com", staff_type="physician", is_active=True)
            hospital = Location(name="Advent Winter Garden", abbreviation="WG", location_type="hospital", is_active=True)
            db.add_all([admin, surgeon, hospital])
            db.flush()
            block_day = date(2026, 7, 13)
            block_id = create_or_blocks(db, BlockORCreateInput(
                name="Open Block",
                start_date=block_day,
                end_date=block_day,
                weekdays=[block_day.weekday()],
                location_ids=[hospital.id],
                session="am",
                start_time=time(7, 0),
                end_time=time(12, 0),
                recurrence="once",
            ), admin_id=admin.id)["instance_ids"][0]
            assign_block(db, block_id, surgeon.id, admin.id)
            db.add(SurgicalCase(
                surgeon_id=surgeon.id,
                or_block_instance_id=block_id,
                date=block_day,
                start_time=time(7, 30),
                end_time=time(8, 30),
                patient_name="Private Patient",
                patient_dob="1/1/1950",
                patient_phone="4075550100",
                procedure="Private procedure",
                location_id=hospital.id,
            ))
            db.commit()

            payload = scheduler_home(block_day.isoformat(), block_day.isoformat(), db=db, admin=admin)
            serialized = str(payload)

            self.assertEqual(payload["range"], {"start": block_day.isoformat(), "end": block_day.isoformat()})
            self.assertEqual(len(payload["blocks"]), 1)
            self.assertEqual(payload["blocks"][0]["surgeonInitials"], "CJ")
            self.assertNotIn("Private Patient", serialized)
            self.assertNotIn("patient_dob", serialized)
            self.assertNotIn("patient_phone", serialized)
            self.assertNotIn("Private procedure", serialized)
            self.assertEqual(len(payload["blocks"][0]["cases"]), 1)
            self.assertEqual(payload["blocks"][0]["cases"][0]["start"], "07:30")
            self.assertEqual(payload["blocks"][0]["cases"][0]["patientName"], "")
            self.assertEqual(payload["blocks"][0]["cases"][0]["procedure"], "")
        finally:
            db.close()

    def test_scheduler_add_case_contract(self):
        db = self.Session()
        try:
            admin = AdminUser(username="admin", email="admin@example.com", password_hash="x", role="admin", is_active=True)
            surgeon = Surgeon(first_name="Alex", last_name="Schroeder", email="alex@example.com", staff_type="physician", is_active=True)
            hospital = Location(name="Advent Winter Garden", abbreviation="WG", location_type="hospital", is_active=True)
            db.add_all([admin, surgeon, hospital])
            db.flush()
            block_day = date(2026, 7, 27)
            block_id = create_or_blocks(db, BlockORCreateInput(
                name="Open Block",
                start_date=block_day,
                end_date=block_day,
                weekdays=[block_day.weekday()],
                location_ids=[hospital.id],
                session="am",
                start_time=time(7, 15),
                end_time=time(10, 45),
                recurrence="once",
            ), admin_id=admin.id)["instance_ids"][0]
            assign_block(db, block_id, surgeon.id, admin.id, assigned_start_time=time(7, 15), case_count=1)

            added = scheduler_add_block_case(
                block_id,
                SchedulerCaseBody(
                    surgeon_id=surgeon.id,
                    start_time="09:15",
                    procedure="Hernia repair",
                    patient_name="Test Patient",
                ),
                db=db,
                admin=admin,
            )
            self.assertTrue(added["ok"])
            self.assertEqual(len(added["block"]["cases"]), 1)
            self.assertEqual(added["block"]["cases"][0]["start"], "09:15")
            self.assertEqual(added["block"]["cases"][0]["procedure"], "Hernia repair")
            self.assertEqual(added["block"]["cases"][0]["patientName"], "Test Patient")
            self.assertEqual(added["block"]["assignments"][0]["caseCount"], 1)
        finally:
            db.close()

    def test_scheduler_clear_assignment_contract(self):
        db = self.Session()
        try:
            admin = AdminUser(username="scheduler", email="scheduler@example.com", password_hash="x", role="scheduler", is_active=True)
            surgeon = Surgeon(first_name="Chris", last_name="Johnson", email="chris@example.com", staff_type="physician", is_active=True)
            hospital = Location(name="Advent Winter Garden", abbreviation="WG", location_type="hospital", is_active=True)
            db.add_all([admin, surgeon, hospital])
            db.flush()
            block_day = date(2026, 7, 13)
            block_id = create_or_blocks(db, BlockORCreateInput(
                name="Open Block",
                start_date=block_day,
                end_date=block_day,
                weekdays=[block_day.weekday()],
                location_ids=[hospital.id],
                session="am",
                start_time=time(7, 0),
                end_time=time(12, 0),
                recurrence="once",
            ), admin_id=admin.id)["instance_ids"][0]
            assign_block(db, block_id, surgeon.id, admin.id, assigned_start_time=time(7, 30), case_count=2)

            payload = scheduler_clear_block_assignment(block_id, db=db, admin=admin)

            self.assertTrue(payload["ok"])
            self.assertEqual(payload["block"]["status"], "open")
            self.assertIsNone(payload["block"]["surgeonId"])
            self.assertEqual(payload["block"]["caseCount"], 0)
        finally:
            db.close()

    def test_scheduler_clear_blocked_when_cases_linked(self):
        db = self.Session()
        try:
            admin = AdminUser(username="admin", email="admin@example.com", password_hash="x", role="admin", is_active=True)
            surgeon = Surgeon(first_name="Alex", last_name="Schroeder", email="alex@example.com", staff_type="physician", is_active=True)
            hospital = Location(name="Advent Winter Garden", abbreviation="WG", location_type="hospital", is_active=True)
            db.add_all([admin, surgeon, hospital])
            db.flush()
            block_day = date(2026, 7, 27)
            block_id = create_or_blocks(db, BlockORCreateInput(
                name="Open Block",
                start_date=block_day,
                end_date=block_day,
                weekdays=[block_day.weekday()],
                location_ids=[hospital.id],
                session="am",
                start_time=time(7, 15),
                end_time=time(10, 45),
                recurrence="once",
            ), admin_id=admin.id)["instance_ids"][0]
            assign_block(db, block_id, surgeon.id, admin.id, assigned_start_time=time(7, 15), case_count=1)
            db.add(SurgicalCase(
                surgeon_id=surgeon.id,
                or_block_instance_id=block_id,
                date=block_day,
                start_time=time(7, 15),
                patient_name="Libby, Ryan",
                procedure="Hernia",
                location_id=hospital.id,
                status="scheduled",
            ))
            db.commit()

            with self.assertRaises(HTTPException) as raised:
                scheduler_clear_block_assignment(block_id, db=db, admin=admin)
            self.assertEqual(raised.exception.status_code, 409)
            self.assertIn("Reschedule", str(raised.exception.detail))
        finally:
            db.close()

    def test_scheduler_create_update_delete_block_contract(self):
        db = self.Session()
        try:
            admin = AdminUser(
                username="scheduler",
                email="scheduler@example.com",
                password_hash="x",
                role="scheduler",
                is_active=True,
            )
            hospital = Location(
                name="Advent Winter Garden",
                abbreviation="WG",
                location_type="hospital",
                is_active=True,
            )
            db.add_all([admin, hospital])
            db.commit()
            block_day = date(2026, 8, 10)

            meta = scheduler_meta(db=db, admin=admin)
            self.assertEqual(len(meta["hospitals"]), 1)
            self.assertEqual(meta["hospitals"][0]["abbreviation"], "WG")

            created = scheduler_create_block(
                SchedulerCreateBlockBody(
                    date=block_day.isoformat(),
                    location_id=hospital.id,
                    session="am",
                    notes="mobile create",
                    room_text="S03",
                ),
                db=db,
                admin=admin,
            )
            self.assertTrue(created["ok"])
            self.assertEqual(created["created"], 1)
            block_id = created["blockIds"][0]
            self.assertEqual(created["blocks"][0]["status"], "open")
            self.assertEqual(created["blocks"][0]["locationAbbreviation"], "WG")
            self.assertEqual(created["blocks"][0]["room"], "S03")

            # Dual capacity: same hospital/day/time, different room is allowed.
            dual = scheduler_create_block(
                SchedulerCreateBlockBody(
                    date=block_day.isoformat(),
                    location_id=hospital.id,
                    session="am",
                    room_text="S08",
                ),
                db=db,
                admin=admin,
            )
            self.assertTrue(dual["ok"])
            self.assertEqual(dual["blocks"][0]["room"], "S08")

            with self.assertRaises(HTTPException) as duplicate_exc:
                scheduler_create_block(
                    SchedulerCreateBlockBody(
                        date=block_day.isoformat(),
                        location_id=hospital.id,
                        session="am",
                        room_text="S03",
                    ),
                    db=db,
                    admin=admin,
                )
            self.assertEqual(duplicate_exc.exception.status_code, 409)

            updated = scheduler_update_block(
                block_id,
                SchedulerUpdateBlockBody(
                    session="pm",
                    start_time="12:00",
                    end_time="17:00",
                    notes="moved pm",
                    room_text="S03",
                ),
                db=db,
                admin=admin,
            )
            self.assertTrue(updated["ok"])
            self.assertEqual(updated["block"]["session"], "pm")
            self.assertEqual(updated["block"]["start"], "12:00")
            self.assertEqual(updated["block"]["notes"], "moved pm")
            self.assertEqual(updated["block"]["room"], "S03")

            dual_id = dual["blockIds"][0]
            deleted = scheduler_delete_block(block_id, db=db, admin=admin)
            self.assertTrue(deleted["ok"])
            self.assertTrue(deleted["deleted"])
            deleted_dual = scheduler_delete_block(dual_id, db=db, admin=admin)
            self.assertTrue(deleted_dual["ok"])
            home = scheduler_home(block_day.isoformat(), block_day.isoformat(), db=db, admin=admin)
            self.assertEqual(home["blocks"], [])
        finally:
            db.close()


if __name__ == "__main__":
    unittest.main()
