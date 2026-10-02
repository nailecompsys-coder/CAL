"""Support preview must show live native data without surgeon OTP or write access."""

import unittest
from datetime import datetime, timedelta, timezone

from fastapi import FastAPI, HTTPException, Response
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from starlette.requests import Request

from app.auth import get_current_admin, get_current_surgeon
from app.auth_tokens import create_surgeon_session_token
from app.database import get_db
from app.models import AdminUser, Base, NativeSupportPreviewGrant, Surgeon, SurgeonDevice
from app.native_support_preview_service import (
    issue_preview_code, redeem_preview_code, surgeon_for_preview_token,
)
from app.routers.native_api import NativeSupportPreviewBody, native_support_preview_exchange, router
from app.routers.admin_surgeons import router as admin_surgeons_router


def _request(method: str, path: str, token: str) -> Request:
    return Request({
        "type": "http",
        "method": method,
        "path": path,
        "headers": [
            (b"authorization", f"Bearer {token}".encode()),
            (b"accept", b"application/json"),
        ],
    })


class NativeSupportPreviewTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite+pysqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.db = sessionmaker(bind=self.engine)()
        self.admin = AdminUser(username="support", email="support@example.com", password_hash="x", role="admin", is_active=True)
        self.surgeon = Surgeon(first_name="Chris", last_name="Johnson", email="chris@example.com", is_active=True)
        self.db.add_all([self.admin, self.surgeon])
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def test_one_use_preview_reads_native_home_but_cannot_write(self):
        code = issue_preview_code(self.db, self.admin, self.surgeon.id)
        self.assertIsNotNone(code)
        token, surgeon = redeem_preview_code(self.db, code, "127.0.0.1")
        self.assertEqual(surgeon.id, self.surgeon.id)
        self.assertIsNone(redeem_preview_code(self.db, code, "127.0.0.1"))
        self.assertEqual(self.db.query(SurgeonDevice).count(), 0)

        for path in ("/api/native/home", "/api/native/patient-schedule"):
            viewed, device = get_current_surgeon(_request("GET", path, token), None, self.db)
            self.assertEqual(viewed.id, self.surgeon.id)
            self.assertIsNone(device)

        for method, path in (
            ("POST", "/api/native/request-off"),
            ("POST", "/api/native/alerts/read"),
            ("GET", "/surgeon/schedule"),
        ):
            with self.assertRaises(HTTPException):
                get_current_surgeon(_request(method, path, token), None, self.db)

        grant = self.db.query(NativeSupportPreviewGrant).one()
        self.assertEqual(grant.admin_user_id, self.admin.id)
        self.assertEqual(grant.surgeon_id, self.surgeon.id)
        self.assertIsNotNone(grant.redeemed_at)
        self.assertEqual(grant.redeemed_ip, "127.0.0.1")

    def test_scheduler_cannot_issue_and_admin_deactivation_revokes_preview(self):
        scheduler = AdminUser(username="scheduler", email="scheduler@example.com", password_hash="x", role="scheduler", is_active=True)
        self.db.add(scheduler)
        self.db.commit()
        self.assertIsNone(issue_preview_code(self.db, scheduler, self.surgeon.id))

        code = issue_preview_code(self.db, self.admin, self.surgeon.id)
        token, _ = redeem_preview_code(self.db, code, None)
        self.admin.is_active = False
        self.db.commit()
        self.assertIsNone(surgeon_for_preview_token(self.db, token))

    def test_exchange_endpoint_never_sends_a_surgeon_otp(self):
        code = issue_preview_code(self.db, self.admin, self.surgeon.id)
        response = Response()
        payload = native_support_preview_exchange(
            NativeSupportPreviewBody(code=code),
            _request("POST", "/api/native/support-preview/exchange", ""),
            response,
            self.db,
        )
        self.assertTrue(payload["readOnly"])
        self.assertEqual(payload["surgeon"]["id"], self.surgeon.id)
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        self.assertEqual(self.db.query(SurgeonDevice).count(), 0)

    def test_expired_code_cannot_be_redeemed(self):
        code = issue_preview_code(self.db, self.admin, self.surgeon.id)
        grant = self.db.query(NativeSupportPreviewGrant).one()
        grant.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        self.db.commit()
        self.assertIsNone(redeem_preview_code(self.db, code, None))

    def test_native_http_route_is_read_only_for_preview(self):
        code = issue_preview_code(self.db, self.admin, self.surgeon.id)
        app = FastAPI()
        app.include_router(router)
        app.dependency_overrides[get_db] = lambda: self.db
        client = TestClient(app)
        exchanged = client.post("/api/native/support-preview/exchange", json={"code": code})
        self.assertEqual(exchanged.status_code, 200)
        token = exchanged.json()["token"]
        headers = {"Authorization": f"Bearer {token}"}
        home = client.get("/api/native/home?start=2026-10-02&end=2026-10-02", headers=headers)
        self.assertEqual(home.status_code, 200)
        self.assertEqual(home.json()["surgeon"]["id"], self.surgeon.id)
        blocked = client.post("/api/native/alerts/read", headers=headers)
        self.assertEqual(blocked.status_code, 401)

    def test_admin_code_is_returned_for_same_page_flyover(self):
        app = FastAPI()
        app.include_router(admin_surgeons_router)
        app.dependency_overrides[get_db] = lambda: self.db
        app.dependency_overrides[get_current_admin] = lambda: self.admin
        response = TestClient(app).post(f"/admin/surgeons/{self.surgeon.id}/native-preview-code")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        self.assertEqual(response.json()["surgeon"], self.surgeon.full_name)
        self.assertEqual(response.json()["expiresMinutes"], 10)
        self.assertEqual(len(response.json()["code"].replace("-", "")), 12)
        self.assertEqual(self.db.query(NativeSupportPreviewGrant).count(), 1)

    def test_retired_browser_preview_route_and_device_cannot_open_schedule(self):
        device = SurgeonDevice(
            surgeon_id=self.surgeon.id,
            device_name="Admin desktop preview",
            token_hash="retired-browser-preview-device",
            is_active=True,
        )
        self.db.add(device)
        self.db.commit()
        token = create_surgeon_session_token(device.id)
        with self.assertRaises(HTTPException):
            get_current_surgeon(_request("GET", "/api/native/home", token), None, self.db)
        stale_cookie_request = Request({
            "type": "http", "method": "GET", "path": "/surgeon/schedule",
            "headers": [(b"cookie", f"surgeon_token_preview={token}".encode())],
        })
        with self.assertRaises(HTTPException):
            get_current_surgeon(stale_cookie_request, None, self.db)

        app = FastAPI()
        app.include_router(admin_surgeons_router)
        app.dependency_overrides[get_db] = lambda: self.db
        app.dependency_overrides[get_current_admin] = lambda: self.admin
        self.assertEqual(
            TestClient(app).post(f"/admin/surgeons/{self.surgeon.id}/preview-mobile").status_code,
            404,
        )


if __name__ == "__main__":
    unittest.main()
