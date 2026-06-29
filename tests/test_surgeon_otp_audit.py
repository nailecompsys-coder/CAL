import os
import unittest
from unittest.mock import patch

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("SECRET_KEY", "test-secret")

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from starlette.requests import Request

from app.models import AdminUser, Base, MagicLink, Surgeon, SurgeonDevice, SurgeonOtpAuditLog
from app.routers.surgeon_otp import (
    OtpRequestBody,
    OtpVerifyBody,
    _otp_sms_message_template,
    _textbelt_otp_userid,
    otp_request,
    otp_verify,
)


def test_request() -> Request:
    return Request({
        "type": "http",
        "method": "POST",
        "path": "/api/surgeon/otp/request",
        "headers": [
            (b"user-agent", b"CALNative/10 Test"),
            (b"x-forwarded-for", b"203.0.113.10"),
        ],
        "client": ("127.0.0.1", 12345),
    })


class SurgeonOtpAuditTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(bind=self.engine)
        self.Session = sessionmaker(bind=self.engine)

    def tearDown(self):
        Base.metadata.drop_all(bind=self.engine)
        self.engine.dispose()

    def test_unknown_email_is_audited_without_creating_otp(self):
        db = self.Session()
        try:
            response = otp_request(OtpRequestBody(email=" wrong@example.com "), request=test_request(), db=db)

            self.assertTrue(response["ok"])
            self.assertEqual(db.query(MagicLink).count(), 0)
            row = db.query(SurgeonOtpAuditLog).one()
            self.assertEqual(row.action, "request")
            self.assertEqual(row.submitted_email, "wrong@example.com")
            self.assertFalse(row.matched)
            self.assertEqual(row.result, "invalid_email")
            self.assertEqual(row.client_ip, "203.0.113.10")
        finally:
            db.close()

    def test_matching_sms_request_is_audited(self):
        db = self.Session()
        try:
            surgeon = Surgeon(first_name="Jorge", last_name="Florin", email="jorge@example.com", phone="4079484000", is_active=True)
            db.add(surgeon)
            db.commit()

            with patch("app.routers.surgeon_otp.generate_sms_otp", return_value=(True, "654321", None)), patch("app.routers.surgeon_otp.send_email", return_value=True):
                response = otp_request(OtpRequestBody(email=" JORGE@example.com "), request=test_request(), db=db)

            self.assertTrue(response["ok"])
            self.assertEqual(db.query(MagicLink).count(), 1)
            self.assertEqual(db.query(MagicLink).one().token_hash, "481f6cc0511143ccdd7e2d1b1b94faf0a700a8b49cd13922a70b5ae28acaa8c5:otp")
            row = db.query(SurgeonOtpAuditLog).one()
            self.assertEqual(row.surgeon_id, surgeon.id)
            self.assertTrue(row.matched)
            self.assertEqual(row.delivery_channel, "sms+email")
            self.assertTrue(row.delivery_success)
            self.assertEqual(row.result, "requested")
        finally:
            db.close()

    def test_sms_message_identifies_cal_code(self):
        self.assertEqual(
            _otp_sms_message_template(),
            "CAL access code: $OTP\nExpires in 15 min. Do not share.",
        )

    def test_textbelt_otp_userid_is_cal_scoped(self):
        surgeon = Surgeon(id=42, first_name="Jorge", last_name="Florin", email="jorge@example.com", is_active=True)
        self.assertEqual(_textbelt_otp_userid(surgeon), "cal:surgeon:42")

    def test_matching_phone_request_is_audited(self):
        db = self.Session()
        try:
            surgeon = Surgeon(first_name="Cindy", last_name="Nguyen", email="cindy@example.com", phone="9102627271", is_active=True)
            db.add(surgeon)
            db.commit()

            with patch("app.routers.surgeon_otp.generate_sms_otp", return_value=(True, "654321", None)), patch("app.routers.surgeon_otp.send_email", return_value=True):
                response = otp_request(OtpRequestBody(email=" (910) 262-7271 "), request=test_request(), db=db)

            self.assertTrue(response["ok"])
            self.assertEqual(db.query(MagicLink).count(), 1)
            row = db.query(SurgeonOtpAuditLog).one()
            self.assertEqual(row.surgeon_id, surgeon.id)
            self.assertEqual(row.submitted_email, "(910) 262-7271")
            self.assertTrue(row.matched)
            self.assertEqual(row.delivery_channel, "sms+email")
            self.assertTrue(row.delivery_success)
            self.assertEqual(row.result, "requested")
        finally:
            db.close()

    def test_sms_request_succeeds_when_email_is_backup_channel(self):
        db = self.Session()
        try:
            surgeon = Surgeon(first_name="Lucy", last_name="Woodley", email="lucy@example.com", phone="4075554960", is_active=True)
            db.add(surgeon)
            db.commit()

            with patch("app.routers.surgeon_otp.generate_sms_otp", return_value=(False, None, "SMS provider failed")), patch("app.routers.surgeon_otp.send_email", return_value=True):
                response = otp_request(OtpRequestBody(email="lucy@example.com"), request=test_request(), db=db)

            self.assertTrue(response["ok"])
            row = db.query(SurgeonOtpAuditLog).one()
            self.assertEqual(row.delivery_channel, "sms+email")
            self.assertTrue(row.delivery_success)
            self.assertEqual(row.result, "requested")
            self.assertIsNone(row.failure_reason)
        finally:
            db.close()

    def test_invalid_verify_is_audited(self):
        db = self.Session()
        try:
            surgeon = Surgeon(first_name="Jorge", last_name="Florin", email="jorge@example.com", phone="4079484000", is_active=True)
            db.add(surgeon)
            db.commit()

            with self.assertRaises(HTTPException):
                otp_verify(OtpVerifyBody(email="jorge@example.com", code="123456"), request=test_request(), db=db)

            row = db.query(SurgeonOtpAuditLog).one()
            self.assertEqual(row.action, "verify")
            self.assertEqual(row.surgeon_id, surgeon.id)
            self.assertEqual(row.result, "invalid_code")
        finally:
            db.close()

    def test_active_admin_email_requests_preview_surgeon_otp(self):
        db = self.Session()
        try:
            preview = Surgeon(first_name="Chris", last_name="Johnson", email="chris@example.com", phone="4073995147", staff_type="physician", sort_order=1, is_active=True)
            hidden_admin_surgeon = Surgeon(first_name="Developer", last_name="Admin", email="don@clermontitstore.com", phone="3526360051", staff_type="physician", sort_order=99, is_active=False)
            admin = AdminUser(username="dnaile", email="don@clermontitstore.com", password_hash="x", is_active=True)
            db.add_all([preview, hidden_admin_surgeon, admin])
            db.commit()

            with patch("app.routers.surgeon_otp.generate_sms_otp", return_value=(True, "123456", None)) as sms, patch("app.routers.surgeon_otp.send_email", return_value=True) as email:
                response = otp_request(OtpRequestBody(email="don@clermontitstore.com"), request=test_request(), db=db)

            self.assertTrue(response["ok"])
            self.assertEqual(sms.call_args.kwargs["phone"], "3526360051")
            self.assertEqual(sms.call_args.kwargs["userid"], f"cal:admin:{admin.id}")
            self.assertEqual(email.call_args.kwargs["to_email"], "don@clermontitstore.com")
            link = db.query(MagicLink).one()
            self.assertEqual(link.surgeon_id, preview.id)
            row = db.query(SurgeonOtpAuditLog).one()
            self.assertEqual(row.submitted_email, "don@clermontitstore.com")
            self.assertEqual(row.surgeon_id, preview.id)
            self.assertEqual(row.delivery_channel, "sms+email")
            self.assertEqual(row.result, "requested")
        finally:
            db.close()

    def test_active_admin_email_can_verify_preview_surgeon_otp(self):
        db = self.Session()
        try:
            preview = Surgeon(first_name="Chris", last_name="Johnson", email="chris@example.com", phone="4073995147", staff_type="physician", sort_order=1, is_active=True)
            admin = AdminUser(username="dnaile", email="don@clermontitstore.com", password_hash="x", is_active=True)
            db.add_all([preview, admin])
            db.commit()

            hidden_admin_surgeon = Surgeon(first_name="Developer", last_name="Admin", email="don@clermontitstore.com", phone="3526360051", staff_type="physician", sort_order=99, is_active=False)
            db.add(hidden_admin_surgeon)
            db.commit()

            with patch("app.routers.surgeon_otp.generate_sms_otp", return_value=(True, "123456", None)) as sms, patch("app.routers.surgeon_otp.send_email", return_value=True):
                otp_request(OtpRequestBody(email="don@clermontitstore.com"), request=test_request(), db=db)
            self.assertEqual(sms.call_args.kwargs["userid"], f"cal:admin:{admin.id}")
            response = otp_verify(OtpVerifyBody(email="don@clermontitstore.com", code="123456"), request=test_request(), db=db)

            self.assertIn("token", response)
            device = db.query(SurgeonDevice).one()
            self.assertEqual(device.surgeon_id, preview.id)
            rows = db.query(SurgeonOtpAuditLog).order_by(SurgeonOtpAuditLog.id).all()
            self.assertEqual([row.result for row in rows], ["requested", "verified"])
        finally:
            db.close()

    def test_successful_verify_creates_device_and_audit(self):
        db = self.Session()
        try:
            surgeon = Surgeon(first_name="Jorge", last_name="Florin", email="jorge@example.com", phone="4079484000", is_active=True)
            db.add(surgeon)
            db.commit()

            with patch("app.routers.surgeon_otp.generate_sms_otp", return_value=(True, "123456", None)), patch("app.routers.surgeon_otp.send_email", return_value=True):
                otp_request(OtpRequestBody(email="jorge@example.com"), request=test_request(), db=db)
            response = otp_verify(OtpVerifyBody(email="jorge@example.com", code="123456"), request=test_request(), db=db)

            self.assertIn("token", response)
            self.assertEqual(db.query(SurgeonDevice).count(), 1)
            rows = db.query(SurgeonOtpAuditLog).order_by(SurgeonOtpAuditLog.id).all()
            self.assertEqual([row.result for row in rows], ["requested", "verified"])
        finally:
            db.close()

    def test_successful_verify_accepts_phone_identifier(self):
        db = self.Session()
        try:
            surgeon = Surgeon(first_name="Lucy", last_name="Woodley", email="lucy@example.com", phone="4075554960", is_active=True)
            db.add(surgeon)
            db.commit()

            with patch("app.routers.surgeon_otp.generate_sms_otp", return_value=(True, "123456", None)), patch("app.routers.surgeon_otp.send_email", return_value=True):
                otp_request(OtpRequestBody(email="407-555-4960"), request=test_request(), db=db)
            response = otp_verify(OtpVerifyBody(email="(407) 555-4960", code="123456"), request=test_request(), db=db)

            self.assertIn("token", response)
            self.assertEqual(db.query(SurgeonDevice).count(), 1)
            rows = db.query(SurgeonOtpAuditLog).order_by(SurgeonOtpAuditLog.id).all()
            self.assertEqual([row.result for row in rows], ["requested", "verified"])
        finally:
            db.close()


if __name__ == "__main__":
    unittest.main()
