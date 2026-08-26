"""Tests for Desk → CAL surgeon-schedule ingest."""
import json
import os
import unittest
from datetime import date, time

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("SECRET_KEY", "test-secret")

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.ingest_resolve import resolve_clinic_location, resolve_or_location, resolve_surgeon
from app.ingest_schedule_service import _block_window_for_cases, ingest_surgeon_schedule
from app.models import AdminNotification, AdminUser, Base, ClinicSchedule, CoSurgeonPair, Location, ORBlockAssignment, ORBlockInstance, Surgeon, SurgicalCase


class IngestScheduleTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)
        self.db = self.Session()
        self.surgeon = Surgeon(
            first_name="Jorge",
            last_name="Florin",
            email="jf@example.com",
            is_active=True,
            staff_type="physician",
        )
        self.ap_or = Location(name="Apopka OR", abbreviation="AP-OR", location_type="hospital", color="#7CBFDE", is_active=True)
        self.ap_cl = Location(name="Apopka Clinic", abbreviation="AP-CL", location_type="clinic", color="#DDF2FC", is_active=True)
        self.hp_cl = Location(name="Health Park", abbreviation="HP-CL", location_type="clinic", color="#DDF2FC", is_active=True)
        self.db.add_all([self.surgeon, self.ap_or, self.ap_cl, self.hp_cl])
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def test_resolve_advent_names_and_rooms(self):
        self.assertEqual(resolve_surgeon(self.db, "Jorge Luis Florin, MD").id, self.surgeon.id)
        self.assertEqual(resolve_or_location(self.db, "APK S03").abbreviation, "AP-OR")
        self.assertNotEqual(resolve_or_location(self.db, "APK S03").id, self.hp_cl.id)

    def test_group_wide_site_code_alone_names_no_clinic(self):
        """AHMGGENSRG is the practice-wide general-surgery code, not a facility."""
        self.assertIsNone(resolve_clinic_location(self.db, "AHMGGENSRG"))

    def test_ocr_misspelled_surgeon_still_resolves(self):
        woodley = Surgeon(
            first_name="Lucy",
            last_name="Woodley",
            email="lw@example.com",
            is_active=True,
            staff_type="physician",
        )
        self.db.add(woodley)
        self.db.commit()
        self.assertEqual(
            resolve_surgeon(self.db, "Lucille Eugenie Woedley, MD").id, woodley.id
        )

    def test_clinic_prefers_surgeon_schedule_over_fax_site(self):
        day = date(2026, 7, 27)
        self.db.add_all([
            ClinicSchedule(
                surgeon_id=self.surgeon.id,
                location_id=self.ap_or.id,
                date=day,
                session="am",
                assignment_type="assigned",
            ),
            ClinicSchedule(
                surgeon_id=self.surgeon.id,
                location_id=self.ap_cl.id,
                date=day,
                session="pm",
                assignment_type="assigned",
            ),
        ])
        self.db.commit()
        loc = resolve_clinic_location(
            self.db,
            "AHMGGENSRG",
            surgeon_id=self.surgeon.id,
            day=day,
            session="pm",
        )
        self.assertEqual(loc.abbreviation, "AP-CL")
        or_loc = resolve_or_location(
            self.db,
            None,
            surgeon_id=self.surgeon.id,
            day=day,
            session="am",
        )
        self.assertEqual(or_loc.abbreviation, "AP-OR")

    def test_block_window_requires_fax_times(self):
        start, end = _block_window_for_cases(
            [{"start_time": "08:30"}, {"start_time": "09:45"}],
            "am",
        )
        self.assertEqual(start, time(8, 30))
        self.assertEqual(end, time(11, 15))
        with self.assertRaises(ValueError):
            _block_window_for_cases([], "am")

    def test_block_window_salvages_time_glued_to_procedure(self):
        """Advent OCR dumps 0715 into Procedure — recover it, don't fail ingest."""
        cases = [
            {"start_time": None, "procedure": "0715 FOREIGN BODY WGD REMOVAL LEFT LOWER"},
            {"start_time": "", "procedure": "0815 EXCISION SOFTTISSUE WGD MASS"},
        ]
        start, end = _block_window_for_cases(cases, "am")
        self.assertEqual(start, time(7, 15))
        self.assertEqual(end, time(9, 45))  # 08:15 + 90m
        self.assertEqual(cases[0]["start_time"], "07:15")
        self.assertEqual(cases[1]["start_time"], "08:15")
        self.assertTrue(cases[0]["procedure"].startswith("FOREIGN BODY"))
        self.assertTrue(cases[1]["procedure"].startswith("EXCISION"))

    def test_five_digit_ocr_clock_recovers_the_real_hhmm(self):
        """Fax #102 Wilkinson: 1015 OCR'd as 91015. Use 10:15, do not invent."""
        cases = [{"start_time": "91015", "procedure": "ROBOTIC RIGHT INGUINAL HERNIA REPAIR"}]
        start, _end = _block_window_for_cases(cases, "am")
        self.assertEqual(start, time(10, 15))
        self.assertEqual(cases[0]["start_time"], "10:15")

    def test_missing_time_goes_to_admin_correction_not_error(self):
        result = ingest_surgeon_schedule(
            self.db,
            source_fax_id=79,
            surgeons=[{
                "surgeon_name": "Jorge Luis Florin, MD",
                "start_date": "2026-08-20",
                "or_block": {
                    "session": "am",
                    "room": "APK S03",
                    "cases": [{
                        "case_date": "2026-08-20",
                        "start_time": None,
                        "patient_name": "Mercer, Kurt",
                        "procedure": "OPEN UMBILICAL HERNIA REPAIR",
                        "room": "APK S03",
                    }],
                },
            }],
        )
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["error_count"], 0)
        self.assertGreaterEqual(result["corrections_count"], 1)
        self.assertEqual(result["corrections"][0]["reason"], "missing_time")
        self.assertEqual(self.db.query(SurgicalCase).count(), 0)

    def test_ocr_name_is_not_an_admin_correction(self):
        """Garbled / truncated names are a parser problem — do not dump them on Shannon."""
        result = ingest_surgeon_schedule(
            self.db,
            source_fax_id=79,
            surgeons=[{
                "surgeon_name": "Jorge Luis Florin, MD",
                "start_date": "2026-08-17",
                "or_block": {
                    "session": "am",
                    "room": "APK S03",
                    "cases": [{
                        "case_date": "2026-08-17",
                        "start_time": "08:15",
                        "patient_name": "Da Silva Ferreira,",
                        "procedure": "EXCISION SOFTTISSUE",
                        "room": "APK S03",
                    }],
                },
            }],
        )
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["error_count"], 0)
        self.assertEqual(self.db.query(SurgicalCase).count(), 1)
        reasons = {row["reason"] for row in result["corrections"]}
        self.assertNotIn("truncated_name", reasons)

    def test_clinic_location_missing_is_correction_not_error(self):
        result = ingest_surgeon_schedule(
            self.db,
            source_fax_id=79,
            surgeons=[{
                "surgeon_name": "Jorge Luis Florin, MD",
                "start_date": "2026-08-17",
                "clinic_rotation": {
                    "session": "pm",
                    "site_raw": "NO_SUCH_SITE",
                    "slots": [{"case_date": "2026-08-17", "patient_name": "X"}],
                },
            }],
        )
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["error_count"], 0)
        self.assertEqual(result["corrections"][0]["reason"], "clinic_location_not_found")

    def test_ingest_creates_block_cases_and_clinic(self):
        day = date(2026, 7, 27)
        self.db.add_all([
            ClinicSchedule(
                surgeon_id=self.surgeon.id,
                location_id=self.ap_or.id,
                date=day,
                session="am",
                assignment_type="assigned",
            ),
            ClinicSchedule(
                surgeon_id=self.surgeon.id,
                location_id=self.ap_cl.id,
                date=day,
                session="pm",
                assignment_type="assigned",
            ),
        ])
        self.db.commit()

        result = ingest_surgeon_schedule(
            self.db,
            source_fax_id=3,
            surgeons=[
                {
                    "surgeon_name": "Jorge Luis Florin, MD",
                    "start_date": "2026-07-27",
                    "or_block": {
                        "session": "am",
                        "room": "APK S03",
                        "cases": [
                            {
                                "case_date": "2026-07-27",
                                "start_time": "08:30",
                                "patient_name": "Sheffield, Martin",
                                "procedure": "Hernia",
                                "room": "APK S03",
                            },
                            {
                                "case_date": "2026-07-27",
                                "start_time": "09:45",
                                "patient_name": "Cruz Mejia, Cristina",
                                "procedure": "Chole",
                                "room": "APK S03",
                            },
                        ],
                    },
                    "clinic_rotation": {
                        "session": "pm",
                        "site_raw": "AHMGGENSRG",
                        "slots": [
                            {
                                "case_date": "2026-07-27",
                                "start_time": "13:00",
                                "patient_name": "Clinic Pt",
                                "site_raw": "AHMGGENSRG",
                            }
                        ],
                    },
                }
            ],
        )
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["blocks_count"], 1)
        self.assertEqual(result["blocks"][0]["action"], "created")
        self.assertEqual(result["cases_count"], 2)
        self.assertEqual(result["clinics_count"], 1)

        block = self.db.query(ORBlockInstance).one()
        self.assertEqual(block.location_id, self.ap_or.id)
        self.assertEqual(block.start_time, time(8, 30))
        self.assertEqual(self.db.query(ORBlockAssignment).count(), 1)
        cases = self.db.query(SurgicalCase).order_by(SurgicalCase.start_time).all()
        self.assertEqual(len(cases), 2)
        self.assertEqual(cases[0].location_id, self.ap_or.id)
        self.assertEqual(cases[0].or_block_instance_id, block.id)
        clinic = self.db.query(ClinicSchedule).filter(ClinicSchedule.session == "pm").one()
        self.assertEqual(clinic.location_id, self.ap_cl.id)
        self.assertIn("13:00", clinic.notes or "")

    def test_ingest_expands_existing_block(self):
        day = date(2026, 7, 27)
        existing = ORBlockInstance(
            series_id=None,
            location_id=self.ap_or.id,
            date=day,
            session="am",
            start_time=time(7, 0),
            end_time=time(10, 0),
            status="open",
            notes="seeded months out",
        )
        self.db.add(existing)
        self.db.commit()

        result = ingest_surgeon_schedule(
            self.db,
            source_fax_id=3,
            surgeons=[
                {
                    "surgeon_name": "Jorge Luis Florin, MD",
                    "start_date": "2026-07-27",
                    "or_block": {
                        "session": "am",
                        "room": "APK S03",
                        "cases": [
                            {
                                "case_date": "2026-07-27",
                                "start_time": "09:00",
                                "patient_name": "Late Case, Pt",
                                "procedure": "Hernia",
                                "room": "APK S03",
                            },
                            {
                                "case_date": "2026-07-27",
                                "start_time": "10:30",
                                "patient_name": "Later Case, Pt",
                                "procedure": "Chole",
                                "room": "APK S03",
                            },
                        ],
                    },
                }
            ],
        )
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["blocks"][0]["action"], "expanded")
        self.assertEqual(self.db.query(ORBlockInstance).count(), 1)
        block = self.db.query(ORBlockInstance).one()
        self.assertEqual(block.start_time, time(7, 0))
        self.assertEqual(block.end_time, time(12, 0))  # 10:30 + 90m
        self.assertEqual(self.db.query(ORBlockAssignment).count(), 1)

    def _co_surgeon_payload(self, surgeon_name, patient="Davenport, Keith"):
        return {
            "surgeon_name": surgeon_name,
            "start_date": "2026-08-10",
            "or_block": {
                "session": "am",
                "room": "APK S04",
                "cases": [
                    {
                        "case_date": "2026-08-10",
                        "start_time": "08:00",
                        "patient_name": patient,
                        "procedure": "Robotic Ventral Hernia Repair",
                        "room": "APK S04",
                    },
                ],
            },
        }

    def _add_froehling_and_pair(self):
        froehling = Surgeon(
            first_name="Nadia",
            last_name="Froehling",
            email="nf@example.com",
            is_active=True,
            staff_type="physician",
        )
        self.db.add(froehling)
        self.db.commit()
        self.db.add(CoSurgeonPair(
            primary_surgeon_id=self.surgeon.id,   # Florin
            assisting_surgeon_id=froehling.id,    # Froehling assists
            is_active=True,
        ))
        self.db.commit()
        return froehling

    def test_co_surgeon_collapses_to_one_case_under_primary(self):
        """Same case under both surgeons → one row under Florin, Froehling as assist."""
        froehling = self._add_froehling_and_pair()
        result = ingest_surgeon_schedule(
            self.db,
            source_fax_id=61,
            surgeons=[
                self._co_surgeon_payload("Jorge Luis Florin, MD"),   # primary first
                self._co_surgeon_payload("Nadia Marie Froehling, MD"),
            ],
        )
        self.assertTrue(result["ok"], result)
        active = self.db.query(SurgicalCase).filter(SurgicalCase.status != "cancelled").all()
        self.assertEqual(len(active), 1, [(c.patient_name, c.surgeon_id) for c in active])
        case = active[0]
        self.assertEqual(case.surgeon_id, self.surgeon.id)          # primary = Florin
        self.assertEqual(case.assisting_surgeon_id, froehling.id)    # assist = Froehling
        self.assertGreaterEqual(result["cases_co_surgeon"], 1)

    def test_co_surgeon_primary_wins_regardless_of_order(self):
        """Even if the assistant's block is ingested first, the case ends under Florin."""
        froehling = self._add_froehling_and_pair()
        result = ingest_surgeon_schedule(
            self.db,
            source_fax_id=61,
            surgeons=[
                self._co_surgeon_payload("Nadia Marie Froehling, MD"),  # assistant first
                self._co_surgeon_payload("Jorge Luis Florin, MD"),
            ],
        )
        self.assertTrue(result["ok"], result)
        active = self.db.query(SurgicalCase).filter(SurgicalCase.status != "cancelled").all()
        self.assertEqual(len(active), 1, [(c.patient_name, c.surgeon_id) for c in active])
        case = active[0]
        self.assertEqual(case.surgeon_id, self.surgeon.id)
        self.assertEqual(case.assisting_surgeon_id, froehling.id)

    def test_cross_surgeon_without_pair_still_skips_duplicate(self):
        """No pairing configured → keep the legacy skip (no second row, no assist)."""
        froehling = Surgeon(
            first_name="Nadia", last_name="Froehling", email="nf2@example.com",
            is_active=True, staff_type="physician",
        )
        self.db.add(froehling)
        self.db.commit()
        result = ingest_surgeon_schedule(
            self.db,
            source_fax_id=61,
            surgeons=[
                self._co_surgeon_payload("Jorge Luis Florin, MD"),
                self._co_surgeon_payload("Nadia Marie Froehling, MD"),
            ],
        )
        self.assertTrue(result["ok"], result)
        active = self.db.query(SurgicalCase).filter(SurgicalCase.status != "cancelled").all()
        self.assertEqual(len(active), 1)
        self.assertIsNone(active[0].assisting_surgeon_id)

    def test_noon_spanning_block_assigns_both_cards(self):
        """An afternoon case must land on the PM card, not a block that ended at noon."""
        result = ingest_surgeon_schedule(
            self.db,
            source_fax_id=4,
            surgeons=[
                {
                    "surgeon_name": "Jorge Luis Florin, MD",
                    "start_date": "2026-07-27",
                    "or_block": {
                        "session": "am",
                        "room": "APK S02",
                        "cases": [
                            {
                                "case_date": "2026-07-27",
                                "start_time": "11:45",
                                "patient_name": "Morning Pt, A",
                                "procedure": "Hernia",
                                "room": "APK S02",
                            },
                            {
                                "case_date": "2026-07-27",
                                "start_time": "13:30",
                                "patient_name": "Afternoon Pt, B",
                                "procedure": "Robotic",
                                "room": "APK S02",
                            },
                        ],
                    },
                }
            ],
        )
        self.assertTrue(result["ok"], result)

        blocks = self.db.query(ORBlockInstance).order_by(ORBlockInstance.start_time).all()
        self.assertEqual([b.session for b in blocks], ["am", "pm"])
        # Every card the fax claims carries the surgeon; none is left open.
        self.assertEqual(self.db.query(ORBlockAssignment).count(), 2)
        self.assertEqual({b.status for b in blocks}, {"assigned"})

        pm_block = blocks[1]
        afternoon = (
            self.db.query(SurgicalCase)
            .filter(SurgicalCase.start_time == time(13, 30))
            .one()
        )
        self.assertEqual(afternoon.or_block_instance_id, pm_block.id)
        self.assertLessEqual(pm_block.start_time, afternoon.start_time)
        self.assertGreater(pm_block.end_time, afternoon.start_time)

    def test_padded_block_tail_does_not_invent_afternoon_card(self):
        """Block end is padded past the last case; padding alone is not OR time."""
        result = ingest_surgeon_schedule(
            self.db,
            source_fax_id=5,
            surgeons=[
                {
                    "surgeon_name": "Jorge Luis Florin, MD",
                    "start_date": "2026-07-27",
                    "or_block": {
                        "session": "am",
                        "room": "APK S05",
                        "cases": [
                            {
                                "case_date": "2026-07-27",
                                "start_time": "11:45",
                                "patient_name": "Only Pt, C",
                                "procedure": "Chole",
                                "room": "APK S05",
                            }
                        ],
                    },
                }
            ],
        )
        self.assertTrue(result["ok"], result)
        blocks = self.db.query(ORBlockInstance).all()
        self.assertEqual(len(blocks), 1)
        self.assertEqual(blocks[0].end_time, time(12, 0))

    def _florin_payload(self, cases, *, start="2026-07-27", end="2026-07-27", clinic=False):
        block = {
            "surgeon_name": "Jorge Luis Florin, MD",
            "start_date": start,
            "end_date": end,
            "or_block": {
                "session": "am",
                "room": "APK S03",
                "cases": cases,
            },
        }
        if clinic:
            block["clinic_rotation"] = {
                "session": "pm",
                "site_raw": "AHMGGENSRG",
                "slots": [
                    {
                        "case_date": start,
                        "start_time": "13:00",
                        "patient_name": "Clinic Pt",
                        "site_raw": "AHMGGENSRG",
                    }
                ],
            }
        return [block]

    def test_reingest_identical_is_ignored(self):
        day = "2026-07-27"
        cases = [
            {
                "case_date": day,
                "start_time": "08:30",
                "patient_name": "Sheffield, Martin",
                "procedure": "Hernia",
                "room": "APK S03",
            }
        ]
        first = ingest_surgeon_schedule(self.db, source_fax_id=3, surgeons=self._florin_payload(cases))
        self.assertEqual(first["cases_created"], 1)
        second = ingest_surgeon_schedule(self.db, source_fax_id=26, surgeons=self._florin_payload(cases))
        self.assertEqual(second["cases_created"], 0)
        self.assertEqual(second["cases_unchanged"], 1)
        self.assertEqual(second["cases_updated"], 0)
        self.assertEqual(self.db.query(SurgicalCase).filter(SurgicalCase.status != "cancelled").count(), 1)
        row = self.db.query(SurgicalCase).one()
        self.assertIn("Desk fax #3", row.notes or "")

    def test_reingest_time_or_room_change_updates(self):
        day = "2026-07-27"
        first_cases = [
            {
                "case_date": day,
                "start_time": "08:30",
                "patient_name": "Sheffield, Martin",
                "procedure": "Hernia",
                "room": "APK S03",
            }
        ]
        ingest_surgeon_schedule(self.db, source_fax_id=3, surgeons=self._florin_payload(first_cases))
        changed = [
            {
                "case_date": day,
                "start_time": "09:00",
                "patient_name": "Sheffield",
                "procedure": "Hernia",
                "room": "APK S05",
            }
        ]
        result = ingest_surgeon_schedule(self.db, source_fax_id=26, surgeons=self._florin_payload(changed))
        self.assertEqual(result["cases_updated"], 1)
        self.assertEqual(self.db.query(SurgicalCase).filter(SurgicalCase.status != "cancelled").count(), 1)
        row = self.db.query(SurgicalCase).one()
        self.assertEqual(row.start_time, time(9, 0))
        self.assertEqual(row.room_text, "APK S05")
        self.assertEqual(row.patient_name, "Sheffield, Martin")

    def test_reingest_removes_missing_desk_case(self):
        day = "2026-07-27"
        first_cases = [
            {
                "case_date": day,
                "start_time": "08:30",
                "patient_name": "Sheffield, Martin",
                "procedure": "Hernia",
                "room": "APK S03",
            },
            {
                "case_date": day,
                "start_time": "09:45",
                "patient_name": "Cruz Mejia, Cristina",
                "procedure": "Chole",
                "room": "APK S03",
            },
        ]
        ingest_surgeon_schedule(self.db, source_fax_id=3, surgeons=self._florin_payload(first_cases))
        only_sheffield = [first_cases[0]]
        result = ingest_surgeon_schedule(
            self.db, source_fax_id=26, surgeons=self._florin_payload(only_sheffield)
        )
        self.assertEqual(result["cases_removed"], 1)
        active = self.db.query(SurgicalCase).filter(SurgicalCase.status != "cancelled").all()
        self.assertEqual(len(active), 1)
        self.assertIn("Sheffield", active[0].patient_name)
        cancelled = self.db.query(SurgicalCase).filter(SurgicalCase.status == "cancelled").one()
        self.assertIn("Cruz", cancelled.patient_name)

    def test_fax_duplicate_lines_do_not_create_second_row(self):
        day = "2026-07-27"
        cases = [
            {
                "case_date": day,
                "start_time": "08:30",
                "patient_name": "Sheffield, Martin",
                "procedure": "Hernia",
                "room": "APK S03",
            },
            {
                "case_date": day,
                "start_time": "08:30",
                "patient_name": "Sheffield",
                "procedure": "Hernia",
                "room": "APK S03",
            },
        ]
        result = ingest_surgeon_schedule(self.db, source_fax_id=26, surgeons=self._florin_payload(cases))
        self.assertEqual(result["cases_created"], 1)
        self.assertEqual(result["cases_unchanged"], 1)
        self.assertEqual(self.db.query(SurgicalCase).count(), 1)

    def test_dob_date_keeps_birthday_and_asks_for_case_clock(self):
        """Wilkinson 07-27-65 is a DOB. Keep it as DOB and flag missing case date/time."""
        admin = AdminUser(username="don", email="don@example.com", password_hash="x", is_active=True)
        self.db.add(admin)
        self.db.commit()
        result = ingest_surgeon_schedule(
            self.db,
            source_fax_id=102,
            surgeons=[{
                "surgeon_name": "Jorge Luis Florin, MD",
                "start_date": "2026-08-25",
                "end_date": "2026-08-28",
                "or_block": {
                    "session": "am",
                    "room": "APK S03",
                    "cases": [
                        {
                            "case_date": "1965-07-27",
                            "start_time": None,
                            "patient_name": "Wilkinson, Llyod",
                            "procedure": "ROBOTIC RIGHT INGUINAL HERNIA REPAIR WITH MESH",
                            "room": "APK S03",
                        },
                        {
                            "case_date": "2026-08-27",
                            "start_time": "13:00",
                            "patient_name": "Madden, David",
                            "procedure": "ROBOTIC CHOLECYSTECTOMY",
                            "room": "APK S03",
                        },
                    ],
                },
            }],
        )
        self.assertTrue(result["ok"], result)
        reasons = [row["reason"] for row in result["corrections"]]
        self.assertIn("missing_time", reasons)
        wilkinson = next(row for row in result["corrections"] if "Wilkinson" in (row.get("body") or ""))
        self.assertIn("DOB 07-27-65", wilkinson["body"])
        self.assertIn("case date or time missing", wilkinson["body"])
        self.assertNotIn("1965-07-27", wilkinson.get("date") or "")
        self.assertEqual(wilkinson["date"], "2026-08-25")
        self.assertGreaterEqual(result["skipped_dates_count"], 1)
        self.assertEqual(result["skipped_dates"][0]["rejected_date"], "1965-07-27")
        rows = self.db.query(SurgicalCase).filter(SurgicalCase.status != "cancelled").all()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].date, date(2026, 8, 27))
        self.assertIn("Madden", rows[0].patient_name)
        note = self.db.query(AdminNotification).filter(
            AdminNotification.kind == "ingest_correction"
        ).first()
        self.assertIsNotNone(note)
        payload = json.loads(note.payload)
        self.assertEqual(payload["patientDob"], "1965-07-27")
        self.assertEqual(payload["date"], "2026-08-25")
        self.assertIn("dob=1965-07-27", payload.get("href") or "")

    def test_fax_case_date_with_dob_flags_missing_clock(self):
        """After reading fax #102: Wilkinson is 8/24/2026, DOB 7/27/65, time OCR junk."""
        admin = AdminUser(username="shannon", email="shannon@example.com", password_hash="x", is_active=True)
        self.db.add(admin)
        self.db.commit()
        result = ingest_surgeon_schedule(
            self.db,
            source_fax_id=102,
            surgeons=[{
                "surgeon_name": "Jorge Luis Florin, MD",
                "start_date": "2026-08-24",
                "end_date": "2026-08-28",
                "or_block": {
                    "session": "am",
                    "room": "APK S03",
                    "cases": [{
                        "case_date": "2026-08-24",
                        "patient_dob": "1965-07-27",
                        "start_time": None,
                        "patient_name": "Wilkinson, Llyod",
                        "procedure": "ROBOTIC RIGHT INGUINAL HERNIA REPAIR WITH MESH",
                        "room": "APK S03",
                    }],
                },
            }],
        )
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["skipped_dates_count"], 0)
        self.assertEqual(self.db.query(SurgicalCase).count(), 0)
        note = self.db.query(AdminNotification).one()
        payload = json.loads(note.payload)
        self.assertEqual(payload["reason"], "missing_time")
        self.assertEqual(payload["date"], "2026-08-24")
        self.assertEqual(payload["patientDob"], "1965-07-27")
        self.assertIn("no start time", note.body)

    def test_ocr_future_year_snaps_into_the_fax_week(self):
        result = ingest_surgeon_schedule(
            self.db,
            source_fax_id=102,
            surgeons=self._florin_payload(
                [{
                    "case_date": "2028-08-27",
                    "start_time": "07:00",
                    "patient_name": "Ferber, Robert",
                    "procedure": "LAPAROSCOPY",
                    "room": "APK S03",
                }],
                start="2026-08-24",
                end="2026-08-28",
            ),
        )
        self.assertTrue(result["ok"], result)
        row = self.db.query(SurgicalCase).one()
        self.assertEqual(row.date, date(2026, 8, 27))

    def test_min_fax_site_maps_to_minneola_clinic(self):
        mn = Location(
            name="Minneola Clinic", abbreviation="MN-OV",
            location_type="clinic", color="#DDF2FC", is_active=True,
        )
        self.db.add(mn)
        self.db.commit()
        self.assertEqual(
            resolve_clinic_location(self.db, "MIN").abbreviation,
            "MN-OV",
        )
        result = ingest_surgeon_schedule(
            self.db,
            source_fax_id=102,
            surgeons=[{
                "surgeon_name": "Jorge Luis Florin, MD",
                "start_date": "2026-08-25",
                "clinic_rotation": {
                    "session": "pm",
                    "site_raw": "MIN",
                    "slots": [{"case_date": "2026-08-25", "patient_name": "X"}],
                },
            }],
        )
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["corrections_count"], 0)
        clinic = self.db.query(ClinicSchedule).one()
        self.assertEqual(clinic.location_id, mn.id)


if __name__ == "__main__":
    unittest.main()
