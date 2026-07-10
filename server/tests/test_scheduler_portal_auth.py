import os
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("SECRET_KEY", "test-secret")

from fastapi import HTTPException
from jose import jwt

from app.auth import get_current_admin
from app.auth_tokens import create_admin_token


class SchedulerPortalAuthTest(unittest.TestCase):
    def _request(self, path: str):
        return SimpleNamespace(
            url=SimpleNamespace(path=path),
            cookies={},
            headers={},
            scope={"path": path, "type": "http"},
        )

    def _admin(self, role: str = "scheduler"):
        return SimpleNamespace(id=9, is_active=True, role=role)

    def test_scheduler_can_open_block_or_and_availability(self):
        admin = self._admin("scheduler")
        token = create_admin_token(admin.id)
        db = MagicMock()
        db.get.return_value = admin
        for path in ("/admin/block-or", "/admin/scheduler-availability", "/admin/logout"):
            result = get_current_admin(self._request(path), admin_token=token, db=db)
            self.assertEqual(result.role, "scheduler")

    def test_scheduler_blocked_from_clinic_schedule(self):
        admin = self._admin("scheduler")
        token = create_admin_token(admin.id)
        db = MagicMock()
        db.get.return_value = admin
        with self.assertRaises(HTTPException):
            get_current_admin(self._request("/admin/clinic-schedule"), admin_token=token, db=db)

    def test_admin_can_open_clinic_schedule(self):
        admin = self._admin("admin")
        token = create_admin_token(admin.id)
        db = MagicMock()
        db.get.return_value = admin
        result = get_current_admin(self._request("/admin/clinic-schedule"), admin_token=token, db=db)
        self.assertEqual(result.role, "admin")


if __name__ == "__main__":
    unittest.main()
