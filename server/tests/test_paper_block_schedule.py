import os
import unittest
from datetime import date, time

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("SECRET_KEY", "test-secret")

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models import Base, ClinicSchedule, DayOff, Location, ORBlockAssignment, ORBlockInstance, Surgeon
from app.paper_block_schedule import (
    PAPER,
    START,
    apply_paper_block_schedule,
    month_week,
    paper_cell,
    paper_or_slots,
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

    def test_off_surgeon_still_placed_on_paper_or_block(self):
        chris = self.db.query(Surgeon).filter_by(last_name="Johnson").one()
        day = date(2026, 9, 21)
        self.db.add(DayOff(
            surgeon_id=chris.id,
            start_date=day,
            end_date=day,
            status="approved",
            reason="day_off",
        ))
        self.db.commit()

        result = apply_paper_block_schedule(
            self.db,
            start=day,
            end=day,
            write_templates=False,
            write_clinic=False,
            write_blocks=True,
        )
        self.assertTrue(result["ok"])
        self.assertGreater(result["skippedOff"], 0)
        self.assertGreater(result["blocksAssigned"], 0)

        clinic = (
            self.db.query(ClinicSchedule)
            .filter_by(surgeon_id=chris.id, date=day)
            .all()
        )
        self.assertEqual(clinic, [])

        mn = self.db.query(Location).filter_by(abbreviation="MN-OR").one()
        blocks = (
            self.db.query(ORBlockInstance)
            .filter_by(location_id=mn.id, date=day)
            .all()
        )
        self.assertEqual(len(blocks), 1)
        self.assertEqual(
            [self.db.get(Surgeon, row.surgeon_id).initials for row in blocks[0].assignments],
            ["CJ"],
        )

    def test_start_is_friday_sep_11(self):
        self.assertEqual(START, date(2026, 9, 11))
        self.assertEqual(month_week(date(2026, 9, 11)), 2)
        self.assertEqual(
            paper_or_slots(date(2026, 9, 11)),
            {
                ("WG-OR", "am"),
                ("AL-OR", "am"),
                ("AL-OR", "pm"),
                ("MN-OR", "pm"),
            },
        )

    def test_friday_sep_11_places_paper_or_and_drops_empty_shells(self):
        al = self.db.query(Location).filter_by(abbreviation="AL-OR").one()
        ap = self.db.query(Location).filter_by(abbreviation="AP-OR").one()
        mn = self.db.query(Location).filter_by(abbreviation="MN-OR").one()
        gy = self.db.query(Surgeon).filter_by(last_name="Yurcisin").one()
        jp = self.db.query(Surgeon).filter_by(last_name="Putnick").one()
        day = date(2026, 9, 11)

        am = ORBlockInstance(
            location_id=al.id,
            date=day,
            session="am",
            start_time=time(7, 0),
            end_time=time(12, 0),
            status="assigned",
            assigned_surgeon_id=gy.id,
            assigned_start_time=time(7, 30),
            assigned_case_count=1,
        )
        empty_ap = ORBlockInstance(
            location_id=ap.id,
            date=day,
            session="am",
            start_time=time(7, 0),
            end_time=time(12, 0),
            status="open",
        )
        mn_pm = ORBlockInstance(
            location_id=mn.id,
            date=day,
            session="pm",
            start_time=time(12, 0),
            end_time=time(13, 30),
            status="assigned",
            room_text="MIN S05",
            assigned_surgeon_id=jp.id,
            assigned_start_time=time(12, 0),
            assigned_case_count=1,
        )
        self.db.add_all([am, empty_ap, mn_pm])
        self.db.flush()
        self.db.add(ORBlockAssignment(
            block_instance_id=am.id,
            surgeon_id=gy.id,
            start_time=time(7, 30),
            case_count=1,
        ))
        self.db.add(ORBlockAssignment(
            block_instance_id=mn_pm.id,
            surgeon_id=jp.id,
            start_time=time(12, 0),
            case_count=1,
        ))
        self.db.commit()

        result = apply_paper_block_schedule(
            self.db,
            start=day,
            end=day,
            write_templates=False,
            write_clinic=False,
            write_blocks=True,
        )
        self.assertTrue(result["ok"])
        self.assertGreater(result["blocksAssigned"], 0)
        self.assertGreaterEqual(result["blocksPruned"], 1)

        self.assertEqual(
            self.db.query(ORBlockInstance).filter_by(location_id=ap.id, date=day).count(),
            0,
        )

        al_blocks = (
            self.db.query(ORBlockInstance)
            .filter_by(location_id=al.id, date=day)
            .order_by(ORBlockInstance.start_time)
            .all()
        )
        self.assertEqual(len(al_blocks), 2)
        am_block = next(row for row in al_blocks if row.start_time < time(12, 0) and row.end_time <= time(12, 0))
        pm_block = next(row for row in al_blocks if row.start_time >= time(12, 0))
        self.assertEqual(
            sorted(self.db.get(Surgeon, row.surgeon_id).initials for row in am_block.assignments),
            ["GY", "LN", "NF"],
        )
        self.assertEqual(
            sorted(self.db.get(Surgeon, row.surgeon_id).initials for row in pm_block.assignments),
            ["GY", "JD", "LN", "NF"],
        )

        wg = self.db.query(Location).filter_by(abbreviation="WG-OR").one()
        wg_blocks = self.db.query(ORBlockInstance).filter_by(location_id=wg.id, date=day).all()
        self.assertEqual(len(wg_blocks), 1)
        self.assertEqual(
            sorted(self.db.get(Surgeon, row.surgeon_id).initials for row in wg_blocks[0].assignments),
            ["JF"],
        )

        mn_blocks = self.db.query(ORBlockInstance).filter_by(location_id=mn.id, date=day).all()
        self.assertEqual(len(mn_blocks), 1)
        self.assertEqual(
            [self.db.get(Surgeon, row.surgeon_id).initials for row in mn_blocks[0].assignments],
            ["JP"],
        )
        self.assertEqual((mn_blocks[0].room_text or "").strip(), "MIN S05")


if __name__ == "__main__":
    unittest.main()
