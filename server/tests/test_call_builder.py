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
    call_history,
    clear_draft,
    publish_changes,
    publish_draft,
    require_admin_call_builder,
    upsert_draft,
)
from app.models import (
    AdminUser,
    Base,
    CallCoverage,
    CallDraftAssignment,
    CallGroup,
    CallRotation,
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
            self.assertIn("Memorial Day/1", by_id[chris.id]["holidays"])
            self.assertEqual(by_id[chris.id]["draftCount"], 2)
            # Month window is December; Chris's published calls are in May — month count 0
            self.assertEqual(by_id[chris.id]["monthCallCount"], 0)
            may = call_history(
                db,
                from_date=date(2026, 1, 1),
                to_date=date(2026, 6, 1),
                draft_from=date(2026, 5, 1),
                draft_to=date(2026, 6, 1),
            )
            may_by = {r["surgeonId"]: r for r in may}
            self.assertEqual(may_by[chris.id]["monthCallCount"], 2)

            self.assertEqual(by_id[nelson.id]["callCount"], 1)
            self.assertIn("July 4th/2", by_id[nelson.id]["holidays"])
            # Alex was covered — not credited
            self.assertEqual(by_id[alex.id]["callCount"], 0)
            # Practice rank order: chris 10, alex 20, nelson 30
            self.assertEqual([r["surgeonId"] for r in rows], [chris.id, alex.id, nelson.id])
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


if __name__ == "__main__":
    unittest.main()
