import os
import unittest
from unittest.mock import MagicMock, Mock, patch

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

from pywebpush import WebPushException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models import Base, NativePushToken, PushSubscription, Surgeon
from app.push import _send_web_push, send_native_push_to_surgeon


class PushCleanupTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(bind=self.engine)
        self.Session = sessionmaker(bind=self.engine)

    def tearDown(self):
        Base.metadata.drop_all(bind=self.engine)
        self.engine.dispose()

    def test_stale_web_push_subscription_is_deleted(self):
        db = self.Session()
        try:
            surgeon = Surgeon(first_name="Chris", last_name="Johnson", email="chris@example.com", is_active=True)
            db.add(surgeon)
            db.flush()
            sub = PushSubscription(
                surgeon_id=surgeon.id,
                endpoint="https://push.example/stale",
                p256dh="key",
                auth_key="auth",
            )
            db.add(sub)
            db.commit()

            response = Mock(status_code=410)
            with patch("app.push.webpush", side_effect=WebPushException("gone", response=response)):
                _send_web_push(sub, "Title", "Body", "/surgeon/schedule", db)

            self.assertEqual(db.query(PushSubscription).count(), 0)
        finally:
            db.close()

    def test_stale_native_token_is_deactivated(self):
        db = self.Session()
        try:
            surgeon = Surgeon(first_name="Chris", last_name="Johnson", email="chris@example.com", is_active=True)
            db.add(surgeon)
            db.flush()
            token = NativePushToken(surgeon_id=surgeon.id, token="ExponentPushToken[stale]", provider="expo", is_active=True)
            db.add(token)
            db.commit()

            response = Mock()
            response.json.return_value = {
                "data": [
                    {
                        "status": "error",
                        "details": {"error": "DeviceNotRegistered"},
                    }
                ]
            }
            with patch("app.push.requests.post", return_value=response):
                send_native_push_to_surgeon(surgeon.id, "Title", "Body", db)

            db.refresh(token)
            self.assertFalse(token.is_active)
        finally:
            db.close()

    def test_stale_apns_token_is_deactivated(self):
        db = self.Session()
        try:
            surgeon = Surgeon(first_name="Chris", last_name="Johnson", email="chris@example.com", is_active=True)
            db.add(surgeon)
            db.flush()
            token = NativePushToken(surgeon_id=surgeon.id, token="apns-stale", provider="apns", is_active=True)
            db.add(token)
            db.commit()

            response = Mock(status_code=410)
            response.json.return_value = {"reason": "Unregistered"}
            client = Mock()
            client.post.return_value = response
            context = MagicMock()
            context.__enter__.return_value = client
            context.__exit__.return_value = False

            with patch("app.push._apns_jwt", return_value="jwt"), patch("app.push.httpx.Client", return_value=context):
                send_native_push_to_surgeon(surgeon.id, "Title", "Body", db)

            db.refresh(token)
            self.assertFalse(token.is_active)
        finally:
            db.close()


if __name__ == "__main__":
    unittest.main()
