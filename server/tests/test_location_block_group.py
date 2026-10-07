import os
import unittest

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("SECRET_KEY", "test-secret")

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models import Base, CallGroup, Location
from app.routers.admin_locations import set_location_group


class LocationBlockGroupTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.db = sessionmaker(bind=self.engine)()
        self.group = CallGroup(name="Winter Garden / Apopka / Minneola Hospital")
        self.clinic = Location(name="Winter Garden Clinic", abbreviation="WG-OV", location_type="clinic", is_active=True)
        self.db.add_all([self.group, self.clinic])
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def test_sets_and_clears_the_block_group(self):
        set_location_group(self.clinic.id, str(self.group.id), db=self.db, admin=None)
        self.db.refresh(self.clinic)
        self.assertEqual(self.clinic.block_group_id, self.group.id)

        set_location_group(self.clinic.id, "", db=self.db, admin=None)
        self.db.refresh(self.clinic)
        self.assertIsNone(self.clinic.block_group_id)

    def test_rejects_an_unknown_group(self):
        response = set_location_group(self.clinic.id, "999", db=self.db, admin=None)
        self.db.refresh(self.clinic)
        self.assertIsNone(self.clinic.block_group_id)
        self.assertIn("invalid_group", response.headers["location"])


if __name__ == "__main__":
    unittest.main()
