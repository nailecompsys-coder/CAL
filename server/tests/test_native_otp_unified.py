"""Contract tests for unified native OTP (no client role toggle)."""

from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth_tokens import decode_subject_token
from app.models import AdminOtpChallenge, AdminUser, Base, MagicLink, Surgeon, SurgeonDevice
from app.routers.native_otp_api import (
    NativeOtpRequestBody,
    NativeOtpVerifyBody,
    native_otp_request,
    native_otp_verify,
)


def _request():
    from starlette.requests import Request

    return Request({
        "type": "http",
        "method": "POST",
        "path": "/api/native/otp/verify",
        "headers": [
            (b"user-agent", b"CAL Native Test"),
        ],
        "client": ("127.0.0.1", 12345),
    })


class NativeOtpUnifiedContractTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite+pysqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)
        self._env = patch.dict(os.environ, {"CAL_LOCAL_DEV_SURGEON_OTP": "", "CAL_LOCAL_DEV_SCHEDULER_OTP": ""})
        self._env.start()

    def tearDown(self):
        self._env.stop()
        self.engine.dispose()

    def test_dual_identity_returns_both_roles_and_tokens(self):
        db = self.Session()
        try:
            surgeon = Surgeon(
                id=14,
                first_name="Don",
                last_name="Naile",
                email="don@clermontitstore.com",
                phone="3526360051",
                staff_type="physician",
                is_active=True,
            )
            admin = AdminUser(
                username="dnaile",
                email="don@clermontitstore.com",
                password_hash="x",
                role="superadmin",
                is_active=True,
            )
            db.add_all([surgeon, admin])
            db.commit()

            with patch("app.routers.native_otp_api.generate_sms_otp", return_value=(True, "123456", None)), patch(
                "app.routers.native_otp_api.send_email", return_value=True
            ):
                requested = native_otp_request(
                    NativeOtpRequestBody(email="don@clermontitstore.com"), db=db
                )
            self.assertEqual(set(requested["roles"]), {"surgeon", "scheduler"})
            self.assertEqual(db.query(MagicLink).count(), 1)
            self.assertEqual(db.query(AdminOtpChallenge).count(), 1)

            verified = native_otp_verify(
                NativeOtpVerifyBody(email="don@clermontitstore.com", code="123456"),
                request=_request(),
                db=db,
            )
            self.assertEqual(set(verified["roles"]), {"surgeon", "scheduler"})
            self.assertEqual(verified["role"], "surgeon")
            self.assertTrue(verified["token"])
            self.assertTrue(verified["tokens"]["surgeon"])
            self.assertTrue(verified["tokens"]["scheduler"])
            self.assertEqual(verified["token"], verified["tokens"]["surgeon"])

            surgeon_payload = decode_subject_token(verified["tokens"]["surgeon"], "surgeon")
            scheduler_payload = decode_subject_token(verified["tokens"]["scheduler"], "native_scheduler")
            self.assertIsInstance(surgeon_payload, int)
            self.assertEqual(scheduler_payload, admin.id)
            self.assertEqual(db.query(SurgeonDevice).count(), 1)
            self.assertEqual(db.query(SurgeonDevice).one().surgeon_id, 14)
        finally:
            db.close()

    def test_surgeon_only_does_not_issue_scheduler_token(self):
        db = self.Session()
        try:
            surgeon = Surgeon(
                first_name="Chris",
                last_name="Johnson",
                email="chris@example.com",
                phone="4073995147",
                is_active=True,
            )
            db.add(surgeon)
            db.commit()

            with patch("app.routers.native_otp_api.generate_sms_otp", return_value=(True, "654321", None)), patch(
                "app.routers.native_otp_api.send_email", return_value=True
            ):
                native_otp_request(NativeOtpRequestBody(email="chris@example.com"), db=db)
            verified = native_otp_verify(
                NativeOtpVerifyBody(email="chris@example.com", code="654321"),
                request=_request(),
                db=db,
            )
            self.assertEqual(verified["roles"], ["surgeon"])
            self.assertEqual(verified["role"], "surgeon")
            self.assertIsNone(verified["tokens"]["scheduler"])
            self.assertTrue(verified["tokens"]["surgeon"])
        finally:
            db.close()

    def test_scheduler_only_does_not_issue_surgeon_token(self):
        db = self.Session()
        try:
            admin = AdminUser(
                username="sched",
                email="scheduler@example.com",
                phone="4075550199",
                password_hash="x",
                role="scheduler",
                is_active=True,
            )
            db.add(admin)
            db.commit()

            with patch("app.routers.native_otp_api.generate_sms_otp", return_value=(True, "111222", None)), patch(
                "app.routers.native_otp_api.send_email", return_value=True
            ):
                requested = native_otp_request(
                    NativeOtpRequestBody(email="scheduler@example.com"), db=db
                )
                self.assertEqual(requested["roles"], ["scheduler"])
                verified = native_otp_verify(
                    NativeOtpVerifyBody(email="scheduler@example.com", code="111222"),
                    request=_request(),
                    db=db,
                )
            self.assertEqual(verified["roles"], ["scheduler"])
            self.assertEqual(verified["role"], "scheduler")
            self.assertIsNone(verified["tokens"]["surgeon"])
            self.assertTrue(verified["tokens"]["scheduler"])
            self.assertEqual(db.query(SurgeonDevice).count(), 0)
        finally:
            db.close()

    def test_admin_and_superadmin_roles_qualify_for_scheduler_shell(self):
        db = self.Session()
        try:
            for role, email in (("admin", "admin@example.com"), ("superadmin", "super@example.com")):
                db.add(
                    AdminUser(
                        username=role,
                        email=email,
                        password_hash="x",
                        role=role,
                        is_active=True,
                    )
                )
            db.commit()
            with patch("app.routers.native_otp_api.generate_sms_otp", return_value=(False, None, None)), patch(
                "app.routers.native_otp_api.send_email", return_value=True
            ):
                for email in ("admin@example.com", "super@example.com"):
                    requested = native_otp_request(NativeOtpRequestBody(email=email), db=db)
                    self.assertEqual(requested["roles"], ["scheduler"])
        finally:
            db.close()

    def test_unknown_identifier_does_not_reveal_and_verify_fails(self):
        db = self.Session()
        try:
            requested = native_otp_request(NativeOtpRequestBody(email="nobody@example.com"), db=db)
            self.assertTrue(requested["ok"])
            self.assertEqual(requested["roles"], [])
            with self.assertRaises(HTTPException) as ctx:
                native_otp_verify(
                    NativeOtpVerifyBody(email="nobody@example.com", code="123456"),
                    request=_request(),
                    db=db,
                )
            self.assertEqual(ctx.exception.status_code, 401)
        finally:
            db.close()

    def test_known_account_delivery_failure_returns_clear_error(self):
        db = self.Session()
        try:
            surgeon = Surgeon(
                first_name="Geoff",
                last_name="Yurcisin",
                email="gyurcisin85@gmail.com",
                phone="4075550100",
                is_active=True,
            )
            db.add(surgeon)
            db.commit()

            with patch("app.routers.native_otp_api.generate_sms_otp", return_value=(False, None, "sms down")), patch(
                "app.routers.native_otp_api.send_email", return_value=False
            ):
                with self.assertRaises(HTTPException) as ctx:
                    native_otp_request(NativeOtpRequestBody(email="gyurcisin85@gmail.com"), db=db)
            self.assertEqual(ctx.exception.status_code, 503)
            self.assertIn("Could not send a code", str(ctx.exception.detail))
        finally:
            db.close()

    def test_local_dev_otp_works_for_dual(self):
        db = self.Session()
        try:
            surgeon = Surgeon(
                first_name="Don",
                last_name="Naile",
                email="don@clermontitstore.com",
                is_active=True,
            )
            admin = AdminUser(
                username="dnaile",
                email="don@clermontitstore.com",
                password_hash="x",
                role="superadmin",
                is_active=True,
            )
            db.add_all([surgeon, admin])
            db.commit()

            with patch.dict(os.environ, {"CAL_LOCAL_DEV_SURGEON_OTP": "654321"}):
                requested = native_otp_request(
                    NativeOtpRequestBody(email="don@clermontitstore.com"), db=db
                )
                self.assertIn("654321", requested["message"])
                verified = native_otp_verify(
                    NativeOtpVerifyBody(email="don@clermontitstore.com", code="654321"),
                    request=_request(),
                    db=db,
                )
            self.assertEqual(set(verified["roles"]), {"surgeon", "scheduler"})
        finally:
            db.close()


class PortalRoleNormalizeTest(unittest.TestCase):
    def test_normalize_keeps_scheduler_admin_superadmin(self):
        from app.admin_settings_user_service import _normalize_role

        self.assertEqual(_normalize_role("scheduler"), "scheduler")
        self.assertEqual(_normalize_role("admin"), "admin")
        self.assertEqual(_normalize_role("superadmin"), "superadmin")
        self.assertEqual(_normalize_role("bogus"), "admin")


class PeopleDropdownTemplateTest(unittest.TestCase):
    def test_people_dropdown_includes_scheduler_and_superadmin(self):
        from pathlib import Path

        src = (
            Path(__file__).resolve().parents[1]
            / "app"
            / "templates"
            / "admin"
            / "settings_people.html"
        ).read_text()
        self.assertIn('option value="scheduler"', src)
        self.assertIn('option value="superadmin"', src)
        self.assertIn('option value="admin"', src)
        self.assertNotIn("this.dataset.role === 'scheduler' ? 'scheduler' : 'admin'", src)


if __name__ == "__main__":
    unittest.main()
