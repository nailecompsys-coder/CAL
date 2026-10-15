import os
import unittest
from datetime import date, time, timedelta
from types import SimpleNamespace

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.admin_clinic_schedule_action_service import assign_clinic, copy_clinic_week
from app.api_calendar_surgeon_service import build_surgeon_calendar_events
from app.surgeon_schedule_queries import surgeon_clinics_by_day
from app.ingest_fix_service import save_ingest_placements
from app.admin_clinic_schedule_page_service import (
    aggregate_assigned_or_blocks,
    build_clinic_grid_slots,
    clinic_fax_overlay_from_notes,
    clinic_schedule_sort_key,
    merge_or_blocks_into_clinic_grid,
    open_block_day_slots,
    page_data,
    parse_clinic_fax_visit_segments,
    set_or_case_counts_on_day_slots,
)
from app.clinic_schedule_card_guard import normalize_clinic_day_cards
from app.migrate_location_admin_fields import normalize_office_location_name
from app.models import (
    Base, ClinicSchedule, Location, ScheduleCard, ScheduleCardActivity, ScheduleCardWeek, Surgeon,
)
from app.or_block_service import BlockORCreateInput, assign_block, create_or_blocks

def _save_card_line(db, surgeon, day, location, start, patient, procedure="Procedure", room=""):
    session = "am" if start < time(12, 0) else "pm"
    week_start = day - timedelta(days=day.weekday())
    week = db.query(ScheduleCardWeek).filter_by(surgeon_id=surgeon.id, week_start=week_start).one_or_none()
    if week is None:
        week = ScheduleCardWeek(surgeon_id=surgeon.id, week_start=week_start)
        db.add(week)
        db.flush()
    card = db.query(ScheduleCard).filter_by(surgeon_id=surgeon.id, date=day, session=session).one_or_none()
    if card is None:
        card = ScheduleCard(
            week_id=week.id,
            surgeon_id=surgeon.id,
            date=day,
            session=session,
            baseline_state="assigned",
            effective_state="assigned",
            baseline_location_id=location.id,
            effective_location_id=location.id,
        )
        db.add(card)
        db.flush()
    key = f"{surgeon.id}-{day.isoformat()}-{start.strftime('%H%M')}-{patient}"
    db.add(ScheduleCardActivity(
        schedule_card_id=card.id,
        surgeon_id=surgeon.id,
        location_id=location.id,
        activity_date=day,
        session=session,
        activity_type="surgical",
        start_time=start,
        patient_name=patient,
        procedure=procedure,
        room_text=room,
        source_system="fax",
        source_record_key=key,
        identity_key=key,
        is_active=True,
    ))


class AdminClinicScheduleTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(bind=self.engine)
        self.Session = sessionmaker(bind=self.engine)

    def tearDown(self):
        Base.metadata.drop_all(bind=self.engine)
        self.engine.dispose()

    def _na_cards(self, db, surgeon, day):
        week_start = day - timedelta(days=day.weekday())
        week = db.query(ScheduleCardWeek).filter_by(
            surgeon_id=surgeon.id, week_start=week_start,
        ).one_or_none()
        if week is None:
            week = ScheduleCardWeek(
                surgeon_id=surgeon.id, week_start=week_start, master_revision="test",
            )
            db.add(week)
            db.flush()
        cards = []
        for session in ("am", "pm"):
            card = db.query(ScheduleCard).filter_by(
                surgeon_id=surgeon.id, date=day, session=session,
            ).one_or_none()
            if card is None:
                card = ScheduleCard(
                    week_id=week.id, surgeon_id=surgeon.id, date=day, session=session,
                    baseline_state="na", effective_state="na",
                )
                db.add(card)
                db.flush()
            cards.append(card)
        return cards

    def test_clinic_schedule_sort_key_places_am_pm_then_full(self):
        rows = [
            ClinicSchedule(id=10, session="pm"),
            ClinicSchedule(id=11, session="full"),
            ClinicSchedule(id=12, session="am"),
        ]

        ordered = sorted(rows, key=clinic_schedule_sort_key)

        self.assertEqual([row.session for row in ordered], ["am", "pm", "full"])

    def test_copy_clinic_week_filters_to_selected_surgeon_only(self):
        db = self.Session()
        try:
            chris = self._surgeon(db, "Chris", "Johnson")
            alex = self._surgeon(db, "Alex", "Schroeder")
            clinic = Location(name="Winter Garden Clinic", abbreviation="WG", location_type="clinic", is_active=True)
            db.add(clinic)
            db.flush()

            today = date.today()
            src_start = today - timedelta(days=today.weekday())
            next_week = src_start + timedelta(days=7)
            chris_src = self._na_cards(db, chris, src_start)
            alex_src = self._na_cards(db, alex, src_start)
            self._na_cards(db, chris, next_week)
            self._na_cards(db, alex, next_week)
            chris_src[0].baseline_state = "assigned"
            chris_src[0].effective_state = "assigned"
            chris_src[0].baseline_location_id = clinic.id
            chris_src[0].effective_location_id = clinic.id
            alex_src[1].baseline_state = "assigned"
            alex_src[1].effective_state = "assigned"
            alex_src[1].baseline_location_id = clinic.id
            alex_src[1].effective_location_id = clinic.id
            db.commit()

            result = copy_clinic_week(db, 0, str(chris.id))

            self.assertTrue(result["ok"])
            self.assertEqual(result["created"], 1)
            copied = db.query(ScheduleCard).filter(
                ScheduleCard.date == next_week,
                ScheduleCard.effective_state == "assigned",
            ).all()
            self.assertEqual(len(copied), 1)
            self.assertEqual(copied[0].surgeon_id, chris.id)
            self.assertEqual(copied[0].session, "am")
        finally:
            db.close()

    def test_edit_existing_assignment_by_id_does_not_leave_old_session(self):
        db = self.Session()
        try:
            surgeon = self._surgeon(db, "Chris", "Johnson")
            clinic = Location(name="Winter Garden Clinic", abbreviation="WG", location_type="clinic", is_active=True)
            hospital = Location(name="Winter Garden OR", abbreviation="WG-OR", location_type="hospital", is_active=True)
            db.add_all([clinic, hospital])
            db.flush()

            schedule_date = date(2026, 7, 8)
            cards = self._na_cards(db, surgeon, schedule_date)
            cards[0].baseline_state = "assigned"
            cards[0].effective_state = "assigned"
            cards[0].baseline_location_id = clinic.id
            cards[0].effective_location_id = clinic.id
            db.commit()

            conflicts = assign_clinic(
                db,
                schedule_date,
                surgeon.id,
                str(hospital.id),
                "pm",
                "new note",
                schedule_id=cards[0].id,
            )

            self.assertEqual(conflicts, [])
            db.refresh(cards[0])
            db.refresh(cards[1])
            self.assertEqual(cards[0].effective_state, "na")
            self.assertEqual(cards[1].effective_state, "assigned")
            self.assertEqual(cards[1].effective_location_id, hospital.id)
            self.assertEqual(cards[1].session, "pm")
        finally:
            db.close()

    def test_whole_day_fills_the_morning_and_afternoon_cards(self):
        db = self.Session()
        try:
            surgeon = self._surgeon(db, "Chris", "Johnson")
            clinic = Location(name="Winter Garden Clinic", abbreviation="WG", location_type="clinic", is_active=True)
            db.add(clinic)
            db.flush()
            schedule_date = date(2026, 7, 8)
            self._na_cards(db, surgeon, schedule_date)
            db.commit()

            conflicts = assign_clinic(
                db, schedule_date, surgeon.id, str(clinic.id), "full", "",
            )

            self.assertEqual(conflicts, [])
            shown = surgeon_clinics_by_day(db, surgeon.id, schedule_date, schedule_date)
            sessions = sorted(card.session for card in shown[schedule_date])
            self.assertEqual(sessions, ["am", "pm"])
            self.assertEqual({card.location.id for card in shown[schedule_date]}, {clinic.id})
            events = [
                event for event in build_surgeon_calendar_events(
                    db, surgeon, schedule_date, schedule_date,
                )
                if str(event["id"]).startswith("clinic-")
            ]
            self.assertEqual(sorted(event["extendedProps"]["session"] for event in events), ["am", "pm"])
            self.assertTrue(all("Winter Garden Clinic" in event["title"] for event in events))
            self.assertEqual(db.query(ClinicSchedule).count(), 0)
        finally:
            db.close()

    def test_schedule_editor_rejects_manual_off_cards(self):
        db = self.Session()
        try:
            surgeon = self._surgeon(db, "Chris", "Johnson")
            schedule_date = date(2026, 7, 8)

            conflicts = assign_clinic(
                db,
                schedule_date,
                surgeon.id,
                "__off__",
                "full",
                "vacation",
            )

            self.assertEqual(
                conflicts,
                ["Use Days Off to mark approved OFF time. Blank schedule slots display as NA."],
            )
            rows = db.query(ClinicSchedule).filter(
                ClinicSchedule.surgeon_id == surgeon.id,
                ClinicSchedule.date == schedule_date,
            ).order_by(ClinicSchedule.session).all()
            self.assertEqual(rows, [])
        finally:
            db.close()

    def test_normalize_day_cards_converts_legacy_full_to_two_slots(self):
        db = self.Session()
        try:
            surgeon = self._surgeon(db, "Chris", "Johnson")
            clinic = Location(name="Winter Garden Clinic", abbreviation="WG-OV", location_type="clinic", is_active=True)
            db.add(clinic)
            db.flush()
            schedule_date = date(2026, 7, 8)
            db.add_all([
                ClinicSchedule(surgeon_id=surgeon.id, location_id=clinic.id, date=schedule_date, session="am", assignment_type="assigned"),
                ClinicSchedule(surgeon_id=surgeon.id, location_id=clinic.id, date=schedule_date, session="full", assignment_type="off"),
            ])
            db.flush()

            normalize_clinic_day_cards(db, surgeon.id, schedule_date)
            db.commit()

            rows = db.query(ClinicSchedule).filter(
                ClinicSchedule.surgeon_id == surgeon.id,
                ClinicSchedule.date == schedule_date,
            ).order_by(ClinicSchedule.session).all()
            self.assertEqual([row.session for row in rows], ["am"])
            self.assertLessEqual(len(rows), 1)
        finally:
            db.close()

    def test_location_name_normalization_changes_office_word_to_clinic(self):
        self.assertEqual(normalize_office_location_name("Winter Garden Office"), "Winter Garden Clinic")
        self.assertEqual(normalize_office_location_name("Office"), "Clinic")
        self.assertEqual(normalize_office_location_name("Main Clinic"), "Main Clinic")

    def test_page_data_indexes_every_block_assignment_by_surgeon(self):
        db = self.Session()
        try:
            hospital = Location(
                name="Advent Winter Garden",
                abbreviation="WG",
                location_type="hospital",
                is_active=True,
            )
            db.add(hospital)
            chris = self._surgeon(db, "Chris", "Johnson")
            jason = self._surgeon(db, "Jason", "Boardman")
            db.flush()
            monday = date.today() - timedelta(days=date.today().weekday())
            block_id = create_or_blocks(
                db,
                BlockORCreateInput(
                    name="Open AM",
                    start_date=monday,
                    end_date=monday,
                    weekdays=[monday.weekday()],
                    location_ids=[hospital.id],
                    session="am",
                    start_time=time(7, 0),
                    end_time=time(12, 0),
                    recurrence="once",
                ),
            )["instance_ids"][0]
            assign_block(db, block_id, chris.id, assigned_start_time=time(7, 0), case_count=1)
            assign_block(db, block_id, jason.id, assigned_start_time=time(9, 0), case_count=2)

            data = page_data(db, week_offset=0)
            chris_blocks = data["assigned_or_blocks"].get(chris.id, {}).get(monday, [])
            jason_blocks = data["assigned_or_blocks"].get(jason.id, {}).get(monday, [])

            self.assertEqual(len(chris_blocks), 1)
            self.assertEqual(len(jason_blocks), 1)
            self.assertEqual(chris_blocks[0]["surgeonId"], chris.id)
            self.assertEqual(chris_blocks[0]["caseCount"], 1)
            self.assertEqual(jason_blocks[0]["surgeonId"], jason.id)
            self.assertEqual(jason_blocks[0]["caseCount"], 2)
            self.assertEqual(jason_blocks[0]["assignedStart"], "09:00")
            self.assertEqual(jason_blocks[0]["pillLabel"], "WG")
            self.assertEqual(jason_blocks[0]["pillCountLabel"], "2 cases")
            self.assertEqual(jason_blocks[0]["session"], "am")
            self.assertEqual(len(jason_blocks[0]["segments"]), 1)
        finally:
            db.close()

    def test_office_board_reads_card_lines(self):
        db = self.Session()
        try:
            hospital = Location(name="Winter Garden OR", abbreviation="WG-OR", location_type="hospital", is_active=True)
            db.add(hospital)
            surgeon = self._surgeon(db, "Chris", "Johnson")
            db.flush()
            monday = date.today() - timedelta(days=date.today().weekday())
            _save_card_line(db, surgeon, monday, hospital, time(8, 0), "Card Line", "New", "WG S01")
            db.commit()
            data = page_data(db, week_offset=0)
            shown = data["surgical_cases_json"].get(f"{surgeon.id}_{monday.isoformat()}", [])
            self.assertEqual([row["patient"] for row in shown], ["Card Line"])
        finally:
            db.close()

    def test_page_data_does_not_surface_unlinked_surgical_cases_as_or_pills(self):
        db = self.Session()
        try:
            hospital = Location(
                name="Minneola OR",
                abbreviation="MN-OR",
                location_type="hospital",
                color="#A7F3D0",
                is_active=True,
            )
            db.add(hospital)
            surgeon = self._surgeon(db, "Alex", "Schroeder")
            db.flush()
            monday = date.today() - timedelta(days=date.today().weekday())
            db.commit()

            data = page_data(db, week_offset=0)
            blocks = data["assigned_or_blocks"].get(surgeon.id, {}).get(monday, [])
            slots = data["clinic_grid_slots"].get(surgeon.id, {}).get(monday, {})

            self.assertEqual(blocks, [])
            self.assertEqual(slots, {})
        finally:
            db.close()

    def test_page_data_does_not_create_pm_pill_for_unlinked_case_against_am_block(self):
        db = self.Session()
        try:
            hospital = Location(
                name="Altamonte OR",
                abbreviation="AL-OR",
                location_type="hospital",
                color="#A7F3D0",
                is_active=True,
            )
            db.add(hospital)
            surgeon = self._surgeon(db, "Nadia", "Froehling")
            db.flush()
            monday = date.today() - timedelta(days=date.today().weekday())
            block_id = create_or_blocks(
                db,
                BlockORCreateInput(
                    name="AM block",
                    start_date=monday,
                    end_date=monday,
                    weekdays=[monday.weekday()],
                    location_ids=[hospital.id],
                    session="am",
                    start_time=time(7, 0),
                    end_time=time(12, 0),
                    recurrence="once",
                ),
            )["instance_ids"][0]
            assign_block(db, block_id, surgeon.id, assigned_start_time=time(7, 0), case_count=0, notify=False)
            db.commit()

            data = page_data(db, week_offset=0)
            blocks = data["assigned_or_blocks"].get(surgeon.id, {}).get(monday, [])
            slots = data["clinic_grid_slots"].get(surgeon.id, {}).get(monday, {})

            self.assertEqual(blocks, [])
            self.assertEqual(slots, {})
        finally:
            db.close()

    def test_ingest_placement_refuses_to_create_missing_master_or_card(self):
        db = self.Session()
        try:
            hospital = Location(
                name="Minneola OR",
                abbreviation="MN-OR",
                location_type="hospital",
                color="#A7F3D0",
                is_active=True,
            )
            db.add(hospital)
            surgeon = self._surgeon(db, "Jason", "Boardman")
            db.flush()
            monday = date.today() - timedelta(days=date.today().weekday())
            block_id = create_or_blocks(
                db,
                BlockORCreateInput(
                    name="Open AM",
                    start_date=monday,
                    end_date=monday,
                    weekdays=[monday.weekday()],
                    location_ids=[hospital.id],
                    session="am",
                    start_time=time(7, 0),
                    end_time=time(12, 0),
                    recurrence="once",
                ),
            )["instance_ids"][0]
            _save_card_line(db, surgeon, monday, hospital, time(7, 15), "Case, Parked")
            db.commit()
            case = db.query(ScheduleCardActivity).filter_by(patient_name="Case, Parked").one()

            result = save_ingest_placements(
                db,
                placements=[{
                    "caseId": case.id,
                    "blockId": block_id,
                    "surgeonId": surgeon.id,
                    "startTime": "07:15",
                }],
            )

            db.refresh(case)
            self.assertFalse(result["ok"])
            self.assertEqual(result["placed"], 0)
            self.assertIn("no existing master OR card", result["errors"][0])
            self.assertIsNone(case.or_block_instance_id)
        finally:
            db.close()

    def test_ingest_placement_can_attach_to_existing_master_or_card(self):
        db = self.Session()
        try:
            hospital = Location(
                name="Minneola OR",
                abbreviation="MN-OR",
                location_type="hospital",
                color="#A7F3D0",
                is_active=True,
            )
            db.add(hospital)
            surgeon = self._surgeon(db, "Jason", "Boardman")
            db.flush()
            monday = date.today() - timedelta(days=date.today().weekday())
            block_id = create_or_blocks(
                db,
                BlockORCreateInput(
                    name="Open AM",
                    start_date=monday,
                    end_date=monday,
                    weekdays=[monday.weekday()],
                    location_ids=[hospital.id],
                    session="am",
                    start_time=time(7, 0),
                    end_time=time(12, 0),
                    recurrence="once",
                ),
            )["instance_ids"][0]
            assign_block(db, block_id, surgeon.id, assigned_start_time=time(7, 0), case_count=0, notify=False)
            _save_card_line(db, surgeon, monday, hospital, time(7, 15), "Case, Parked")
            db.commit()
            case = db.query(ScheduleCardActivity).filter_by(patient_name="Case, Parked").one()

            result = save_ingest_placements(
                db,
                placements=[{
                    "caseId": case.id,
                    "blockId": block_id,
                    "surgeonId": surgeon.id,
                    "startTime": "07:15",
                    "room": "MIN S05",
                }],
            )

            db.refresh(case)
            self.assertTrue(result["ok"])
            self.assertEqual(result["placed"], 1)
            self.assertEqual(case.or_block_instance_id, block_id)
            self.assertEqual(case.location_id, hospital.id)
        finally:
            db.close()

    def test_page_data_hides_zero_case_paper_or_cards(self):
        db = self.Session()
        try:
            clinic = Location(
                name="Lake Mary Clinic",
                abbreviation="LM-OV",
                location_type="clinic",
                color="#BFDBFE",
                is_active=True,
            )
            hospital = Location(
                name="Altamonte OR",
                abbreviation="AL-OR",
                location_type="hospital",
                color="#A7F3D0",
                is_active=True,
            )
            db.add_all([clinic, hospital])
            surgeon = self._surgeon(db, "Geoff", "Yurcisin")
            db.flush()
            monday = date.today() - timedelta(days=date.today().weekday())
            db.add(ClinicSchedule(
                surgeon_id=surgeon.id,
                location_id=clinic.id,
                date=monday,
                session="am",
                assignment_type="assigned",
            ))
            for session, start, end in (("am", time(7, 0), time(12, 0)), ("pm", time(12, 0), time(17, 0))):
                block_id = create_or_blocks(
                    db,
                    BlockORCreateInput(
                        name=f"{session.upper()} paper block",
                        start_date=monday,
                        end_date=monday,
                        weekdays=[monday.weekday()],
                        location_ids=[hospital.id],
                        session=session,
                        start_time=start,
                        end_time=end,
                        recurrence="once",
                    ),
                )["instance_ids"][0]
                assign_block(db, block_id, surgeon.id, assigned_start_time=start, case_count=0, assignment_note="Paper block schedule", notify=False)
            db.commit()

            data = page_data(db, week_offset=0)
            blocks = data["assigned_or_blocks"].get(surgeon.id, {}).get(monday, [])
            entries = data["sched_map"].get(surgeon.id, {}).get(monday, [])

            self.assertEqual([(entry.session, entry.location.abbreviation) for entry in entries], [("am", "LM-OV")])
            self.assertEqual(blocks, [])
        finally:
            db.close()

    def test_page_data_enforces_two_card_daily_limit(self):
        db = self.Session()
        try:
            clinic = Location(
                name="Lake Mary Clinic",
                abbreviation="LM-OV",
                location_type="clinic",
                color="#BFDBFE",
                is_active=True,
            )
            hospital = Location(
                name="Altamonte OR",
                abbreviation="AL-OR",
                location_type="hospital",
                color="#A7F3D0",
                is_active=True,
            )
            db.add_all([clinic, hospital])
            surgeon = self._surgeon(db, "Geoff", "Yurcisin")
            db.flush()
            monday = date.today() - timedelta(days=date.today().weekday())
            db.add_all([
                ClinicSchedule(
                    surgeon_id=surgeon.id,
                    location_id=hospital.id,
                    date=monday,
                    session="am",
                    assignment_type="assigned",
                ),
                ClinicSchedule(
                    surgeon_id=surgeon.id,
                    location_id=clinic.id,
                    date=monday,
                    session="pm",
                    assignment_type="assigned",
                ),
            ])
            _save_card_line(db, surgeon, monday, hospital, time(7, 30), "Alvarado, Hunter", "Case 1", "ALT S07")
            db.commit()

            data = page_data(db, week_offset=0)
            entries = data["sched_map"].get(surgeon.id, {}).get(monday, [])
            blocks = data["assigned_or_blocks"].get(surgeon.id, {}).get(monday, [])
            overlays = data["or_block_overlays"]

            self.assertEqual(len(entries), 2)
            self.assertEqual([(row.session, row.location.abbreviation) for row in entries], [("am", "AL-OR"), ("pm", "LM-OV")])
            self.assertEqual(blocks, [])
            self.assertEqual(overlays[entries[0].id]["pillLabel"], "AL-OR")
            self.assertEqual(overlays[entries[0].id]["caseCount"], 1)
            self.assertLessEqual(len(entries) + len(blocks), 2)
            self.assertNotIn(entries[1].id, overlays)
        finally:
            db.close()

    def test_page_data_never_returns_full_as_third_visible_card(self):
        db = self.Session()
        try:
            clinic = Location(
                name="Winter Garden Clinic",
                abbreviation="WG-OV",
                location_type="clinic",
                color="#BFDBFE",
                is_active=True,
            )
            hospital = Location(
                name="Winter Garden OR",
                abbreviation="WG-OR",
                location_type="hospital",
                color="#E48EA6",
                is_active=True,
            )
            db.add_all([clinic, hospital])
            surgeon = self._surgeon(db, "Jorge", "Florin")
            db.flush()
            monday = date.today() - timedelta(days=date.today().weekday())
            db.add_all([
                ClinicSchedule(
                    surgeon_id=surgeon.id,
                    location_id=hospital.id,
                    date=monday,
                    session="full",
                    assignment_type="assigned",
                ),
                ClinicSchedule(
                    surgeon_id=surgeon.id,
                    location_id=clinic.id,
                    date=monday,
                    session="pm",
                    assignment_type="assigned",
                ),
            ])
            _save_card_line(db, surgeon, monday, hospital, time(7, 15), "Case One", "Procedure", "WG S01")
            db.commit()

            data = page_data(db, week_offset=0)
            entries = data["sched_map"].get(surgeon.id, {}).get(monday, [])
            blocks = data["assigned_or_blocks"].get(surgeon.id, {}).get(monday, [])
            sessions = [row.session for row in entries]

            self.assertEqual(len(entries) + len(blocks), 2)
            self.assertEqual(sessions, ["am", "pm"])
            self.assertEqual(data["or_block_overlays"][entries[0].id]["pillCountLabel"], "1 case")
        finally:
            db.close()

    def test_existing_hospital_card_gets_case_count_without_extra_card(self):
        db = self.Session()
        try:
            hospital = Location(
                name="Winter Garden OR",
                abbreviation="WG-OR",
                location_type="hospital",
                color="#E48EA6",
                is_active=True,
            )
            db.add(hospital)
            surgeon = self._surgeon(db, "Jorge", "Florin")
            db.flush()
            monday = date.today() - timedelta(days=date.today().weekday())
            schedule = ClinicSchedule(
                surgeon_id=surgeon.id,
                location_id=hospital.id,
                date=monday,
                session="am",
                assignment_type="assigned",
            )
            db.add(schedule)
            _save_card_line(db, surgeon, monday, hospital, time(7, 15), "Case One", "Procedure", "WG S01")
            _save_card_line(db, surgeon, monday, hospital, time(9, 0), "Case Two", "Procedure", "WG S01")
            db.commit()

            data = page_data(db, week_offset=0)
            entries = data["sched_map"].get(surgeon.id, {}).get(monday, [])
            blocks = data["assigned_or_blocks"].get(surgeon.id, {}).get(monday, [])
            overlay = data["or_block_overlays"].get(schedule.id)

            self.assertEqual(len(entries), 1)
            self.assertEqual(blocks, [])
            self.assertIsNotNone(overlay)
            self.assertEqual(overlay["pillLabel"], "WG-OR")
            self.assertEqual(overlay["pillCountLabel"], "2 cases")
            self.assertEqual([seg["patient"] for seg in overlay["segments"]], ["Case One", "Case Two"])
        finally:
            db.close()

    def test_grid_slots_pick_one_card_per_am_pm_even_with_duplicate_inputs(self):
        day = date(2026, 9, 15)
        hospital = Location(
            id=10,
            name="Winter Garden OR",
            abbreviation="WG-OR",
            location_type="hospital",
            color="#E48EA6",
            is_active=True,
        )
        clinic = Location(
            id=11,
            name="Winter Garden Clinic",
            abbreviation="WG-OV",
            location_type="clinic",
            color="#BFDBFE",
            is_active=True,
        )
        plain_or = ClinicSchedule(
            id=100,
            surgeon_id=3,
            location_id=hospital.id,
            date=day,
            session="am",
            assignment_type="assigned",
        )
        counted_or = ClinicSchedule(
            id=101,
            surgeon_id=3,
            location_id=hospital.id,
            date=day,
            session="am",
            assignment_type="assigned",
        )
        clinic_row = ClinicSchedule(
            id=102,
            surgeon_id=3,
            location_id=clinic.id,
            date=day,
            session="pm",
            assignment_type="assigned",
        )
        plain_or.location = hospital
        counted_or.location = hospital
        clinic_row.location = clinic

        slots = build_clinic_grid_slots(
            {3: {day: [plain_or, counted_or, clinic_row]}},
            {
                3: {
                    day: [{
                        "detailId": "fallback-wg",
                        "session": "am",
                        "assignedStart": "07:15",
                        "caseCount": 3,
                        "locationAbbreviation": "WG-OR",
                    }]
                }
            },
            {
                counted_or.id: {
                    "caseCount": 3,
                    "pillLabel": "WG-OR",
                    "pillCountLabel": "3 cases",
                }
            },
            {},
        )

        day_slots = slots[3][day]
        self.assertEqual(day_slots["am"]["entry"].id, counted_or.id)
        self.assertIsNone(day_slots["am"]["block"])
        self.assertEqual(day_slots["pm"]["entry"].id, clinic_row.id)
        self.assertIsNone(day_slots["pm"]["block"])

    def test_grid_slots_ignore_legacy_off_schedule_rows(self):
        day = date(2026, 9, 18)
        off_am = ClinicSchedule(
            id=200,
            surgeon_id=15,
            date=day,
            session="am",
            assignment_type="off",
        )
        off_pm = ClinicSchedule(
            id=201,
            surgeon_id=15,
            date=day,
            session="pm",
            assignment_type="off",
        )

        slots = build_clinic_grid_slots(
            {15: {day: [off_am, off_pm]}},
            {
                15: {
                    day: [{
                        "detailId": "unlinked-min",
                        "session": "pm",
                        "assignedStart": "07:15",
                        "caseCount": 1,
                        "locationAbbreviation": "MIN-OR",
                    }]
                }
            },
            {},
            {},
        )

        day_slots = slots[15][day]
        self.assertIsNone(day_slots["am"]["entry"])
        self.assertIsNone(day_slots["am"]["block"])
        self.assertIsNone(day_slots["pm"]["entry"])
        self.assertEqual(day_slots["pm"]["block"]["detailId"], "unlinked-min")

    def test_aggregate_assigned_or_blocks_merges_same_location_session(self):
        merged = aggregate_assigned_or_blocks([
            {
                "id": 1,
                "date": "2026-07-13",
                "session": "am",
                "surgeonId": 7,
                "locationId": 3,
                "location": "Winter Garden OR",
                "locationAbbreviation": "WG-OR",
                "locationColor": "#E48EA6",
                "assignedStart": "09:00",
                "caseCount": 2,
                "assignmentNote": "",
                "assignmentLabel": "WG-OR - 09:00 - 2 Cases",
                "assignmentId": 11,
            },
            {
                "id": 1,
                "date": "2026-07-13",
                "session": "am",
                "surgeonId": 7,
                "locationId": 3,
                "location": "Winter Garden OR",
                "locationAbbreviation": "WG-OR",
                "locationColor": "#E48EA6",
                "assignedStart": "07:00",
                "caseCount": 1,
                "assignmentNote": "",
                "assignmentLabel": "WG-OR - 07:00 - 1 Case",
                "assignmentId": 10,
            },
            {
                "id": 2,
                "date": "2026-07-13",
                "session": "pm",
                "surgeonId": 7,
                "locationId": 3,
                "location": "Winter Garden OR",
                "locationAbbreviation": "WG-OR",
                "locationColor": "#E48EA6",
                "assignedStart": "13:00",
                "caseCount": 1,
                "assignmentNote": "late",
                "assignmentLabel": "WG-OR - 13:00 - 1 Case",
                "assignmentId": 12,
            },
        ])
        self.assertEqual(len(merged), 2)
        am = next(row for row in merged if row["session"] == "am")
        pm = next(row for row in merged if row["session"] == "pm")
        self.assertEqual(am["caseCount"], 3)
        self.assertEqual(am["assignedStart"], "07:00")
        self.assertEqual(am["pillLabel"], "WG-OR")
        self.assertEqual(am["pillCountLabel"], "3 cases")
        self.assertEqual(len(am["segments"]), 2)
        self.assertEqual(pm["pillLabel"], "WG-OR")
        self.assertEqual(pm["pillCountLabel"], "1 case")
        self.assertEqual(pm["assignmentNote"], "late")

    def test_merge_or_block_into_clinic_grid_pill(self):
        day = date(2026, 7, 27)
        ap_or = Location(id=8, name="Apopka OR", abbreviation="AP-OR", location_type="hospital", is_active=True)
        schedule = ClinicSchedule(
            id=100,
            surgeon_id=13,
            location_id=8,
            date=day,
            session="am",
            assignment_type="assigned",
        )
        schedule.location = ap_or
        sched_map = {13: {day: [schedule]}}
        assigned = {
            13: {
                day: [{
                    "detailId": "agg-13-8-am-2026-07-27",
                    "surgeonId": 13,
                    "locationId": 8,
                    "location": "Apopka OR",
                    "locationAbbreviation": "AP-OR",
                    "session": "am",
                    "assignedStart": "08:30",
                    "caseCount": 2,
                    "pillLabel": "AP-OR",
                    "pillCountLabel": "2 cases",
                    "startCompact": "0830",
                    "segments": [],
                }]
            }
        }
        overlays, remaining = merge_or_blocks_into_clinic_grid(sched_map, assigned)
        self.assertEqual(overlays[100]["pillLabel"], "AP-OR")
        self.assertEqual(overlays[100]["pillCountLabel"], "2 cases")
        self.assertEqual(remaining, {})

    def test_open_block_day_slots_one_pill_per_or(self):
        hospitals = [
            SimpleNamespace(id=1, abbreviation="AL-OR", name="Altamonte OR", color="#79CDBD"),
            SimpleNamespace(id=2, abbreviation="AP-OR", name="Apopka OR", color="#C4B5FD"),
            SimpleNamespace(id=3, abbreviation="MN-OR", name="Minneola OR", color="#FDBA74"),
            SimpleNamespace(id=4, abbreviation="WG-OR", name="Winter Garden OR", color="#E48EA6"),
        ]
        day = date(2026, 7, 11)
        by_day = {
            day: {
                3: [
                    {
                        "id": 50,
                        "start": "07:00",
                        "end": "12:00",
                        "status": "open",
                        "caseCount": 0,
                    }
                ],
                4: [
                    {
                        "id": 51,
                        "start": "07:00",
                        "end": "12:00",
                        "status": "assigned",
                        "caseCount": 2,
                    },
                    {
                        "id": 52,
                        "start": "09:00",
                        "end": "12:00",
                        "status": "assigned",
                        "caseCount": 1,
                    },
                ],
            }
        }
        slots = open_block_day_slots(hospitals, by_day, day)
        self.assertEqual(len(slots), 4)
        self.assertEqual(slots[0]["status"], "empty")
        self.assertIsNone(slots[0]["blockId"])
        mn = slots[2]
        self.assertEqual(mn["locationAbbreviation"], "MN-OR")
        self.assertEqual(mn["timeLabel"], "7:00-12:00")
        self.assertEqual(mn["caseCount"], 0)
        self.assertEqual(mn["caseCountLabel"], "0 cases")
        self.assertEqual(mn["blockId"], 50)
        wg = slots[3]
        self.assertEqual(wg["timeLabel"], "7:00-12:00")
        self.assertEqual(wg["caseCount"], 3)
        self.assertEqual(wg["caseCountLabel"], "3 cases")
        self.assertEqual(wg["blockId"], 51)

    def test_open_block_day_slots_use_only_real_hospital_cases(self):
        day = date(2026, 9, 16)
        location = Location(
            id=8,
            name="Apopka OR",
            abbreviation="AP-OR",
            location_type="hospital",
            color="#7CBFDE",
            is_active=True,
        )
        slots = {
            day: [{
                "locationId": 8,
                "locationAbbreviation": "AP-OR",
                "timeLabel": "7:00-17:00",
                "caseCount": 9,
                "caseCountLabel": "9 cases",
                "pillTitle": "AP-OR 7:00-17:00 · 9 cases",
            }]
        }
        surgical_map = {
            16: {
                day: [
                    ScheduleCardActivity(
                        surgeon_id=16,
                        activity_date=day,
                        session="am",
                        activity_type="surgical",
                        start_time=time(7, 15),
                        patient_name="Philome, Natasha",
                        procedure="",
                        location_id=8,
                        location=location,
                        source_system="test",
                        source_record_key="philome",
                        identity_key="philome",
                        is_active=True,
                    ),
                    ScheduleCardActivity(
                        surgeon_id=16,
                        activity_date=day,
                        session="am",
                        activity_type="surgical",
                        start_time=time(8, 15),
                        patient_name="Arent, Tadeusz",
                        procedure="",
                        location_id=8,
                        location=location,
                        source_system="test",
                        source_record_key="arent",
                        identity_key="arent",
                        is_active=True,
                    ),
                    ScheduleCardActivity(
                        surgeon_id=16,
                        activity_date=day,
                        session="am",
                        activity_type="surgical",
                        start_time=time(9, 15),
                        patient_name="Linked case",
                        procedure="",
                        location_id=8,
                        location=location,
                        source_system="test",
                        source_record_key="linked",
                        identity_key="linked",
                        is_active=True,
                    ),
                ]
            }
        }

        updated = set_or_case_counts_on_day_slots(slots, surgical_map)

        self.assertEqual(updated[day][0]["caseCount"], 3)
        self.assertEqual(updated[day][0]["caseCountLabel"], "3 cases")
        self.assertIn("3 cases", updated[day][0]["pillTitle"])

    def test_open_block_day_slots_exclude_clinic_rows(self):
        day = date(2026, 9, 23)
        hospital = Location(
            id=8,
            name="Apopka OR",
            abbreviation="AP-OR",
            location_type="hospital",
            is_active=True,
        )
        clinic = Location(
            id=4,
            name="Apopka Office",
            abbreviation="AP-OV",
            location_type="clinic",
            is_active=True,
        )
        slots = {
            day: [{
                "locationId": 8,
                "locationAbbreviation": "AP-OR",
                "timeLabel": None,
                "caseCount": 7,
                "caseCountLabel": "7 cases",
                "pillTitle": "AP-OR · 7 cases",
            }]
        }
        surgical_map = {
            16: {day: [
                ScheduleCardActivity(
                    surgeon_id=16,
                    activity_date=day,
                    session="am",
                    activity_type="surgical",
                    start_time=time(7, 15),
                    patient_name="OR patient",
                    procedure="Procedure",
                    location_id=8,
                    location=hospital,
                    source_system="test",
                    source_record_key="or-patient",
                    identity_key="or-patient",
                    is_active=True,
                ),
                ScheduleCardActivity(
                    surgeon_id=16,
                    activity_date=day,
                    session="am",
                    activity_type="surgical",
                    start_time=time(8, 30),
                    patient_name="Clinic patient",
                    procedure="Office visit",
                    location_id=4,
                    location=clinic,
                    source_system="test",
                    source_record_key="clinic-patient",
                    identity_key="clinic-patient",
                    is_active=True,
                ),
            ]}
        }

        updated = set_or_case_counts_on_day_slots(slots, surgical_map)

        self.assertEqual(updated[day][0]["caseCount"], 1)
        self.assertEqual(updated[day][0]["caseCountLabel"], "1 case")

    def test_clinic_fax_notes_include_patient_names(self):
        notes = (
            "Desk fax #26 · Kno2 pxrjw4bczqiluegrhlyogzina3puwc2xtvnb6gaa · source=desk · "
            "13:00 NIEVES, ROSA CAROLINA; 13:10 PINDER, MARJORIE PAMELA; 13:20 CTA; "
            "13:30 GONZALEZ, LUIS; 13:50 HATTER; 14:00 New AHMGGENSRG CORRALES, MAGDA; "
            "14:30 ABD EL RAHMAN, GENERAL; 15:00 MARTINEZ CORRALES, MAGDA; 15:20 ZEPEDA"
        )
        segments = parse_clinic_fax_visit_segments(notes)
        self.assertEqual(len(segments), 9)
        self.assertEqual(segments[0]["start"], "13:00")
        self.assertEqual(segments[0]["label"], "NIEVES, ROSA CAROLINA")
        self.assertEqual(segments[2]["label"], "CTA")
        self.assertEqual(segments[-1]["label"], "ZEPEDA")

        clinic = Location(
            name="Apopka Clinic",
            abbreviation="AP-CL",
            location_type="clinic",
            is_active=True,
        )
        schedule = ClinicSchedule(
            id=1515,
            session="pm",
            assignment_type="assigned",
            notes=notes,
            location=clinic,
            location_id=4,
        )
        overlay = clinic_fax_overlay_from_notes(schedule)
        self.assertIsNotNone(overlay)
        self.assertEqual(overlay["caseCount"], 9)
        self.assertEqual(overlay["segments"][0]["label"], "NIEVES, ROSA CAROLINA")

    def test_visual_sot_clinic_notes_include_patient_names(self):
        notes = "Fax 162 visual SOT · 08:30 FLORES, ANNA MARIE; 08:40 DAMON, BRANDY JUSTICE; 08:50 MARTINEZ, GARI"
        segments = parse_clinic_fax_visit_segments(notes)
        self.assertEqual(len(segments), 3)
        self.assertEqual(segments[0]["label"], "FLORES, ANNA MARIE")

        clinic = Location(
            name="HP Clermont Clinic",
            abbreviation="CL-OV",
            location_type="clinic",
            is_active=True,
        )
        schedule = ClinicSchedule(
            id=2115,
            session="am",
            assignment_type="assigned",
            notes=notes,
            location=clinic,
            location_id=13,
        )
        overlay = clinic_fax_overlay_from_notes(schedule)
        self.assertIsNotNone(overlay)
        self.assertEqual(overlay["caseCount"], 3)
        self.assertEqual(overlay["pillLabel"], "CL-OV")
        self.assertEqual(overlay["pillCountLabel"], "3 visits")

    def _surgeon(self, db, first_name, last_name):
        row = Surgeon(
            first_name=first_name,
            last_name=last_name,
            email=f"{first_name.lower()}.{last_name.lower()}@example.com",
            is_active=True,
            staff_type="physician",
        )
        db.add(row)
        db.flush()
        return row


if __name__ == "__main__":
    unittest.main()
