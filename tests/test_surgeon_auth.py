import os
import unittest

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("SECRET_KEY", "test-secret")

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from starlette.requests import Request

from app.auth import create_surgeon_session_token, get_current_surgeon
from app.models import Base, Surgeon, SurgeonDevice


class SurgeonAuthTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(bind=self.engine)
        self.Session = sessionmaker(bind=self.engine)

    def tearDown(self):
        Base.metadata.drop_all(bind=self.engine)
        self.engine.dispose()

    def test_native_bearer_token_wins_over_stale_cookie(self):
        db = self.Session()
        try:
            surgeon = Surgeon(
                first_name="Jorge",
                last_name="Florin",
                email="jorge@example.com",
                staff_type="physician",
                is_active=True,
            )
            db.add(surgeon)
            db.flush()
            active_device = SurgeonDevice(
                surgeon_id=surgeon.id,
                device_name="CAL iPhone app",
                user_agent="CALNative/11",
                token_hash="active",
                is_active=True,
            )
            db.add(active_device)
            db.commit()

            valid_token = create_surgeon_session_token(active_device.id)
            stale_cookie = create_surgeon_session_token(999999)
            request = Request({
                "type": "http",
                "method": "GET",
                "path": "/api/native/home",
                "headers": [
                    (b"authorization", f"Bearer {valid_token}".encode()),
                    (b"cookie", f"surgeon_token={stale_cookie}".encode()),
                    (b"accept", b"application/json"),
                ],
                "client": ("127.0.0.1", 12345),
            })

            current_surgeon, current_device = get_current_surgeon(request=request, db=db)

            self.assertEqual(current_surgeon.id, surgeon.id)
            self.assertEqual(current_device.id, active_device.id)
        finally:
            db.close()


if __name__ == "__main__":
    unittest.main()
