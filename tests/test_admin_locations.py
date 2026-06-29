import os
import unittest

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("SECRET_KEY", "test-secret")

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api_calendar_utils import location_abbrev
from app.models import Base, Location
from app.routers.admin_locations import add_location, edit_location


class AdminLocationsTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(bind=self.engine)
        self.Session = sessionmaker(bind=self.engine)

    def tearDown(self):
        Base.metadata.drop_all(bind=self.engine)
        self.engine.dispose()

    def test_add_location_accepts_admin_color_and_abbreviation(self):
        db = self.Session()
        try:
            response = add_location(
                name="New Specialty Clinic",
                abbreviation="mh jp",
                address="",
                city="",
                phone="",
                location_type="clinic",
                color="#aabbcc",
                db=db,
                admin=object(),
            )

            self.assertEqual(response.status_code, 303)
            loc = db.query(Location).one()
            self.assertEqual(loc.name, "New Specialty Clinic")
            self.assertEqual(loc.abbreviation, "MH JP")
            self.assertEqual(loc.color, "#AABBCC")
            self.assertEqual(location_abbrev(loc), "MH JP")
        finally:
            db.close()

    def test_add_location_rejects_invalid_color(self):
        db = self.Session()
        try:
            response = add_location(
                name="New Specialty Clinic",
                abbreviation="NS",
                address="",
                city="",
                phone="",
                location_type="clinic",
                color="blue",
                db=db,
                admin=object(),
            )

            self.assertEqual(response.status_code, 303)
            self.assertEqual(response.headers["location"], "/admin/locations?msg=invalid_color")
            self.assertEqual(db.query(Location).count(), 0)
        finally:
            db.close()

    def test_add_location_rejects_invalid_abbreviation(self):
        db = self.Session()
        try:
            response = add_location(
                name="New Specialty Clinic",
                abbreviation="TOO_LONG_FOR_UI",
                address="",
                city="",
                phone="",
                location_type="clinic",
                color="#AABBCC",
                db=db,
                admin=object(),
            )

            self.assertEqual(response.status_code, 303)
            self.assertEqual(response.headers["location"], "/admin/locations?msg=invalid_abbreviation")
            self.assertEqual(db.query(Location).count(), 0)
        finally:
            db.close()

    def test_edit_location_updates_admin_fields(self):
        db = self.Session()
        try:
            loc = Location(name="Old", abbreviation="OLD", location_type="clinic", color="#D8F6F0", is_active=True)
            db.add(loc)
            db.commit()

            response = edit_location(
                location_id=loc.id,
                name="Altamonte Hospital",
                abbreviation="alt",
                address="1 Main",
                city="Altamonte",
                phone="4075550100",
                location_type="hospital",
                color="#79cdbd",
                db=db,
                admin=object(),
            )

            self.assertEqual(response.status_code, 303)
            db.refresh(loc)
            self.assertEqual(loc.abbreviation, "ALT")
            self.assertEqual(loc.location_type, "hospital")
            self.assertEqual(loc.color, "#79CDBD")
        finally:
            db.close()


if __name__ == "__main__":
    unittest.main()
