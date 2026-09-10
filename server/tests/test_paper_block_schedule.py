import os
import unittest
from datetime import date

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("SECRET_KEY", "test-secret")

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models import Base, ClinicSchedule, DayOff, Location, ORBlockAssignment, ORBlockInstance, Surgeon
from app.paper_block_schedule import (
    PAPER,
    apply_paper_block_schedule,
    month_week,
    paper_cell,
)


def _loc(db, abbrev, name, loc_type):
    row = Location(name=name, abbreviation=abbrev, location_type=loc_type, is_active=True)
    db.add(row)
    db.flush()
    return row


def _doc(db, first, last):
    row = Surgeon(
        first_name=first,
        last_name=last,
        email=f"{first[0].lower()}{last[0].lower()}@example.com",
        is_active=True,
        staff_type="physician",
    )
    db.add(row)
    db.flush()
    return row


class PaperBlockScheduleTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)
        self.db = self.Session()
        for abbrev, name, kind in (
            ("AP-OR", "Apopka OR", "hospital"),
            ("AP-OV", "Apopka Clinic", "clinic"),
            ("WG-OR", "Winter Garden OR", "hospital"),
            ("WG-OV", "Winter Garden Clinic", "clinic"),
            ("MN-OR", "Minneola OR", "hospital"),
            ("CL-OV", "HP Clermont Clinic", "clinic"),
            ("DP-OV", "Dr. Phillips Clinic", "clinic"),
            ("AL-OV", "Altamonte Clinic", "clinic"),
            ("AL-OR", "Altamonte OR", "hospital"),
            ("LM-OV", "Lake Mary Clinic", "clinic"),
        ):
            _loc(self.db, abbrev, name, kind)
        names = {
            "JF": ("Jorge", "Florin"),
            "CJ": ("Chris", "Johnson"),
            "JB": ("Jason", "Boardman"),
            "AS": ("Alex", "Schroeder"),
            "OK": ("Owen", "Kieran"),
            "LW": ("Lucy", "Woodley"),
            "JP": ("Jennine", "Putnick"),
            "GY": ("Geoff", "Yurcisin"),
            "LN": ("Lars", "Nelson"),
            "NF": ("Nadia", "Froehling"),
            "JD": ("Jonathan", "Dean"),
        }
        for _initials, (first, last) in names.items():
            _doc(self.db, first, last)
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def test_month_week_sep_14_is_week_2(self):
        self.assertEqual(month_week(date(2026, 9, 7)), 1)
        self.assertEqual(month_week(date(2026, 9, 14)), 2)
        self.assertEqual(month_week(date(2026, 9, 21)), 3)
        self.assertEqual(month_week(date(2026, 9, 28)), 4)

    def test_alex_wg_or_only_weeks_1_3_5(self):
        self.assertIsNone(paper_cell("AS", date(2026, 9, 14), "am"))
        self.assertEqual(paper_cell("AS", date(2026, 9, 14), "pm"), "CL-OV")
        self.assertEqual(paper_cell("AS", date(2026, 9, 21), "am"), "WG-OR")
        self.assertEqual(paper_cell("AS", date(2026, 9, 18), "am"), "WG-OR")
        self.assertIsNone(paper_cell("AS", date(2026, 9, 11), "am"))

    def test_clermont_is_clinic_never_or(self):
        self.assertEqual(paper_cell("JB", date(2026, 9, 14), "am"), "CL-OV")
        self.assertFalse(any(
            spec[0] == "CL-OR"
            for cells in PAPER.values()
            for spec in cells.values()
        ))

    def test_apply_writes_clinic_and_skips_day_off(self):
        alex = self.db.query(Surgeon).filter_by(last_name="Schroeder").one()
        self.db.add(DayOff(
            surgeon_id=alex.id,
            start_date=date(2026, 9, 14),
            end_date=date(2026, 9, 14),
            status="approved",
            reason="CME / Conference",
        ))
        self.db.commit()

        result = apply_paper_block_schedule(
            self.db,
            start=date(2026, 9, 14),
            end=date(2026, 9, 18),
            write_templates=True,
            write_clinic=True,
            write_blocks=False,
        )
        self.assertTrue(result["ok"])
        self.assertGreater(result["skippedOff"], 0)

        jorge = self.db.query(Surgeon).filter_by(last_name="Florin").one()
        mon = (
            self.db.query(ClinicSchedule)
            .filter_by(surgeon_id=jorge.id, date=date(2026, 9, 14), session="am")
            .one()
        )
        self.assertEqual(mon.location.abbreviation, "AP-OR")

        alex_mon = (
            self.db.query(ClinicSchedule)
            .filter_by(surgeon_id=alex.id, date=date(2026, 9, 14))
            .all()
        )
        self.assertEqual(alex_mon, [])

        chris = self.db.query(Surgeon).filter_by(last_name="Johnson").one()
        fri = (
            self.db.query(ClinicSchedule)
            .filter_by(surgeon_id=chris.id, date=date(2026, 9, 18))
            .all()
        )
        self.assertEqual(fri, [])

    def test_two_surgeons_share_one_time_block_not_two_rooms(self):
        result = apply_paper_block_schedule(
            self.db,
            start=date(2026, 9, 15),
            end=date(2026, 9, 15),
            write_templates=False,
            write_clinic=True,
            write_blocks=True,
        )
        self.assertTrue(result["ok"])
        wg = self.db.query(Location).filter_by(abbreviation="WG-OR").one()
        blocks = (
            self.db.query(ORBlockInstance)
            .filter(
                ORBlockInstance.location_id == wg.id,
                ORBlockInstance.date == date(2026, 9, 15),
            )
            .all()
        )
        self.assertEqual(len(blocks), 1)
        self.assertFalse((blocks[0].room_text or "").strip())
        assigned = sorted(
            self.db.get(Surgeon, row.surgeon_id).initials
            for row in blocks[0].assignments
        )
        self.assertEqual(assigned, ["CJ", "JF"])


if __name__ == "__main__":
    unittest.main()
