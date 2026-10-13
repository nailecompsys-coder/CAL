import os
import unittest
from datetime import date
from unittest.mock import patch

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("SECRET_KEY", "test-secret")

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.call_builder_service import (
    _history_statement,
    attach_holiday_grids,
    attach_leave_to_history,
    call_history,
    clear_draft,
    holiday_work_lookup,
    leave_flag_map,
    leave_groups_by_date,
    leave_label,
    leave_entries_by_date,
    publish_changes,
    publish_draft,
    require_admin_call_builder,
    resolve_surgeon_id_by_initials,
    upsert_draft,
)
from app.models import (
    AdminUser,
    Base,
    CallCoverage,
    CallDraftAssignment,
    CallGroup,
    CallRotation,
    DayOff,
    Holiday,
    Surgeon,
)


class CallBuilderTest(unittest.TestCase):
    def setUp(self):
        _history_statement.cache_clear()
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(bind=self.engine)
        self.Session = sessionmaker(bind=self.engine)

    def tearDown(self):
        Base.metadata.drop_all(bind=self.engine)
        self.engine.dispose()

    def _seed(self, db):
        admin = AdminUser(
            username="cjohnson",
            email="chris@example.com",
            password_hash="x",
            first_name="Chris",
            last_name="Johnson",
            role="admin",
            can_call_builder=True,
        )
        blocked = AdminUser(
            username="angel",
            email="angel@example.com",
            password_hash="x",
            first_name="Angelina",
            last_name="Sanders",
            role="scheduler",
            can_call_builder=False,
        )
        chris = Surgeon(
            first_name="Christopher",
            last_name="Johnson",
            email="cj@example.com",
            is_active=True,
            staff_type="physician",
            can_call_builder=True,
            sort_order=10,
        )
        alex = Surgeon(
            first_name="Alex",
            last_name="Schroeder",
            email="as@example.com",
            is_active=True,
            staff_type="physician",
            sort_order=20,
        )
        nelson = Surgeon(
            first_name="Larry",
            last_name="Nelson",
            email="ln@example.com",
            is_active=True,
            staff_type="physician",
            sort_order=30,
        )
        wg = CallGroup(name="Winter Garden / Apopka / Minneola Hospital", sort_order=0)
        alt = CallGroup(name="Altamonte Hospital", sort_order=1)
        db.add_all([admin, blocked, chris, alex, nelson, wg, alt])
        db.add(Holiday(date=date(2026, 5, 25), name="Memorial Day"))
        db.add(Holiday(date=date(2026, 7, 4), name="July 4th"))
        db.commit()
        return admin, blocked, chris, alex, nelson, wg, alt

    def test_access_gate_and_draft_does_not_touch_rotations(self):
        db = self.Session()
        try:
            admin, blocked, chris, alex, _, wg, _ = self._seed(db)
            with self.assertRaises(HTTPException) as ctx:
                require_admin_call_builder(blocked)
            self.assertEqual(ctx.exception.status_code, 403)

            day = date(2026, 12, 5)
            upsert_draft(db, day=day, call_group_id=wg.id, surgeon_id=chris.id, admin=admin)
            self.assertEqual(db.query(CallDraftAssignment).count(), 1)
            self.assertEqual(db.query(CallRotation).count(), 0)

            clear_draft(db, day=day, call_group_id=wg.id, admin=admin)
            self.assertEqual(db.query(CallDraftAssignment).count(), 0)
            self.assertEqual(db.query(CallRotation).count(), 0)

            with self.assertRaises(HTTPException):
                upsert_draft(db, day=day, call_group_id=wg.id, surgeon_id=alex.id, admin=blocked)
        finally:
            db.close()

    def test_history_sql_counts_coverage_weekends_and_holidays(self):
        db = self.Session()
        try:
            _, _, chris, alex, nelson, wg, alt = self._seed(db)
            # Chris: Sat May 23 + Memorial Day (Mon) WG
            db.add(CallRotation(date=date(2026, 5, 23), call_group_id=wg.id, surgeon_id=chris.id))
            db.add(CallRotation(date=date(2026, 5, 25), call_group_id=wg.id, surgeon_id=chris.id))
            # Alex assigned July 4; Nelson covers — credit Nelson
            july = CallRotation(date=date(2026, 7, 4), call_group_id=alt.id, surgeon_id=alex.id)
            db.add(july)
            db.commit()
            db.refresh(july)
            db.add(CallCoverage(
                call_rotation_id=july.id,
                original_surgeon_id=alex.id,
                covering_surgeon_id=nelson.id,
                status="active",
            ))
            # Draft for Chris in December
            db.add(CallDraftAssignment(date=date(2026, 12, 4), call_group_id=wg.id, surgeon_id=chris.id))
            db.add(CallDraftAssignment(date=date(2026, 12, 5), call_group_id=wg.id, surgeon_id=chris.id))
            db.commit()

            rows = call_history(
                db,
                from_date=date(2026, 1, 1),
                to_date=date(2026, 12, 1),
                draft_from=date(2026, 12, 1),
                draft_to=date(2027, 1, 1),
            )
            by_id = {r["surgeonId"]: r for r in rows}
            self.assertEqual(by_id[chris.id]["callCount"], 2)
            self.assertEqual(by_id[chris.id]["weekendCount"], 1)
            self.assertEqual(by_id[chris.id]["holidayCount"], 1)
            self.assertEqual(by_id[chris.id]["lastHoliday"], "Memorial Day")
            self.assertEqual(by_id[chris.id]["lastHolidayAbbrev"], "Mem")
            self.assertEqual(by_id[chris.id]["loadLine"], "2/1 · 0/0 · 1/Mem")
            self.assertIn("Memorial Day/1", by_id[chris.id]["holidays"])
            self.assertEqual(by_id[chris.id]["draftCount"], 2)
            # Month window is December; Chris's published calls are in May — month count 0
            self.assertEqual(by_id[chris.id]["monthCallCount"], 0)
            self.assertEqual(by_id[chris.id]["monthWeekendCount"], 0)
            may = call_history(
                db,
                from_date=date(2026, 1, 1),
                to_date=date(2026, 6, 1),
                draft_from=date(2026, 5, 1),
                draft_to=date(2026, 6, 1),
            )
            may_by = {r["surgeonId"]: r for r in may}
            self.assertEqual(may_by[chris.id]["monthCallCount"], 2)
            self.assertEqual(may_by[chris.id]["monthWeekendCount"], 1)
            self.assertEqual(may_by[chris.id]["loadLine"], "2/1 · 2/1 · 1/Mem")

            self.assertEqual(by_id[nelson.id]["callCount"], 1)
            self.assertEqual(by_id[nelson.id]["holidayCount"], 1)
            self.assertEqual(by_id[nelson.id]["lastHolidayAbbrev"], "Jul4")
            self.assertIn("July 4th/2", by_id[nelson.id]["holidays"])
            # Alex was covered — not credited
            self.assertEqual(by_id[alex.id]["callCount"], 0)
            self.assertEqual(by_id[alex.id]["loadLine"], "0/0 · 0/0 · 0/—")
            # Practice rank order: chris 10, alex 20, nelson 30
            self.assertEqual([r["surgeonId"] for r in rows], [chris.id, alex.id, nelson.id])
        finally:
            db.close()


    def test_surgeon_draft_persists_on_board(self):
        db = self.Session()
        try:
            _, _, chris, alex, _, wg, alt = self._seed(db)
            day = date(2026, 12, 8)
            upsert_draft(db, day=day, call_group_id=wg.id, surgeon_id=chris.id, surgeon=chris)
            from app.call_builder_service import board_for_month
            board = board_for_month(db, 2026, 12)
            self.assertEqual(board["draftCount"], 1)
            cell = next(
                c for c in board["cells"]
                if c["date"] == day.isoformat() and c["callGroupId"] == wg.id
            )
            self.assertEqual(cell["source"], "draft")
            self.assertEqual(cell["surgeonId"], chris.id)
            clear_draft(db, day=day, call_group_id=wg.id, surgeon=chris)
            board2 = board_for_month(db, 2026, 12)
            self.assertEqual(board2["draftCount"], 0)
        finally:
            db.close()

    def test_publish_writes_live_and_clears_draft(self):
        db = self.Session()
        try:
            admin, _, chris, alex, _, wg, alt = self._seed(db)
            day = date(2026, 12, 12)
            upsert_draft(db, day=day, call_group_id=wg.id, surgeon_id=chris.id, admin=admin)
            upsert_draft(db, day=day, call_group_id=alt.id, surgeon_id=alex.id, admin=admin)
            changes = publish_changes(db, date(2026, 12, 1), date(2026, 12, 31))
            self.assertEqual(len(changes), 2)
            with patch("app.admin_call_schedule_action_service.send_push_to_surgeon"):
                warnings = publish_draft(
                    db, start=date(2026, 12, 1), end=date(2026, 12, 31), admin=admin,
                )
            self.assertEqual(warnings, [])
            self.assertEqual(db.query(CallDraftAssignment).count(), 0)
            live = db.query(CallRotation).filter(CallRotation.date == day).all()
            by_group = {r.call_group_id: r.surgeon_id for r in live}
            self.assertEqual(by_group[wg.id], chris.id)
            self.assertEqual(by_group[alt.id], alex.id)
        finally:
            db.close()

    def test_holiday_grid_credits_coverage_year(self):
        db = self.Session()
        try:
            _, _, chris, alex, nelson, wg, alt = self._seed(db)
            # _seed already has Memorial Day 2026-05-25 and July 4th 2026-07-04
            db.add(Holiday(date=date(2025, 12, 24), name="Christmas Eve"))
            db.add(CallRotation(date=date(2026, 5, 25), call_group_id=wg.id, surgeon_id=chris.id))
            july = CallRotation(date=date(2026, 7, 4), call_group_id=alt.id, surgeon_id=alex.id)
            db.add(july)
            db.commit()
            db.refresh(july)
            db.add(CallCoverage(
                call_rotation_id=july.id,
                original_surgeon_id=alex.id,
                covering_surgeon_id=nelson.id,
                status="active",
            ))
            db.commit()
            work = holiday_work_lookup(db)
            self.assertEqual(work[(chris.id, "Memorial Day", 2026)], "WG")
            self.assertEqual(work[(nelson.id, "July 4th", 2026)], "ALT")
            self.assertNotIn((alex.id, "July 4th", 2026), work)
            history = [{"surgeonId": chris.id}, {"surgeonId": alex.id}, {"surgeonId": nelson.id}]
            attach_holiday_grids(history, work)
            mem = next(r for r in history[0]["holidayGrid"] if r["name"] == "Memorial Day")
            self.assertEqual(mem["cells"][1], "WG")  # 2026
            self.assertIn("Memorial Day 2026 (WG)", history[0]["holidaysWorked"])
            self.assertEqual(history[1]["holidaysWorked"], [])
            self.assertIn("July 4th 2026 (ALT)", history[2]["holidaysWorked"])
        finally:
            db.close()

    def test_resolve_surgeon_id_by_initials(self):
        db = self.Session()
        try:
            _, _, chris, alex, _, _, _ = self._seed(db)
            self.assertEqual(resolve_surgeon_id_by_initials(db, "cj"), chris.id)
            self.assertEqual(resolve_surgeon_id_by_initials(db, " AS "), alex.id)
            with self.assertRaises(HTTPException) as missing:
                resolve_surgeon_id_by_initials(db, "ZZ")
            self.assertEqual(missing.exception.status_code, 400)
            with self.assertRaises(HTTPException) as short:
                resolve_surgeon_id_by_initials(db, "C")
            self.assertEqual(short.exception.status_code, 400)
        finally:
            db.close()

    def test_leave_labels_vacation_and_no_call(self):
        self.assertEqual(leave_label("Vacation"), "Vacation")
        self.assertEqual(leave_label("no_call"), "No Call")
        self.assertEqual(leave_label("Day Off"), "Off")
        self.assertEqual(leave_label("day_off"), "Off")
        self.assertEqual(leave_label("Personal"), "Personal")

        db = self.Session()
        try:
            _, _, chris, alex, nelson, _, _ = self._seed(db)
            day = date(2026, 12, 15)
            db.add_all([
                DayOff(
                    surgeon_id=chris.id, start_date=day, end_date=day,
                    reason="Vacation", status="approved",
                ),
                DayOff(
                    surgeon_id=alex.id, start_date=day, end_date=day,
                    reason="Day Off", status="approved",
                ),
                DayOff(
                    surgeon_id=nelson.id, start_date=day, end_date=day,
                    reason="No Call", status="approved",
                ),
                # Pending must not appear
                DayOff(
                    surgeon_id=chris.id,
                    start_date=date(2026, 12, 16),
                    end_date=date(2026, 12, 16),
                    reason="Vacation",
                    status="pending",
                ),
            ])
            db.commit()
            leave = leave_flag_map(db, date(2026, 12, 1), date(2026, 12, 31))
            self.assertEqual(leave[f"2026-12-15|{chris.id}"], "Vacation")
            self.assertEqual(leave[f"2026-12-15|{alex.id}"], "Off")
            self.assertEqual(leave[f"2026-12-15|{nelson.id}"], "No Call")
            self.assertNotIn(f"2026-12-16|{chris.id}", leave)

            surgeons = {chris.id: chris, alex.id: alex, nelson.id: nelson}
            by_date = leave_entries_by_date(
                db, date(2026, 12, 1), date(2026, 12, 31), surgeons=surgeons,
            )
            groups = leave_groups_by_date(by_date)["2026-12-15"]
            by_short = {g["short"]: g["initialsLine"] for g in groups}
            self.assertEqual(by_short["NC"], nelson.initials)
            self.assertEqual(by_short["VAC"], chris.initials)
            self.assertEqual(by_short["OFF"], alex.initials)

            history = [
                {"surgeonId": chris.id, "leaveLabels": [], "leaveLine": ""},
                {"surgeonId": alex.id, "leaveLabels": [], "leaveLine": ""},
            ]
            attach_leave_to_history(history, leave)
            self.assertEqual(history[0]["leaveLine"], "Vacation")
            self.assertEqual(history[1]["leaveLine"], "Off")
        finally:
            db.close()


if __name__ == "__main__":
    unittest.main()
