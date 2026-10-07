import os
import unittest
from datetime import date

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("SECRET_KEY", "test-secret")

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.call_builder_service import (
    call_history,
    clear_draft,
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
        )
        alex = Surgeon(
            first_name="Alex",
            last_name="Schroeder",
            email="as@example.com",
            is_active=True,
            staff_type="physician",
        )
        nelson = Surgeon(
            first_name="Larry",
            last_name="Nelson",
            email="ln@example.com",
            is_active=True,
            staff_type="physician",
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

            self.assertEqual(by_id[nelson.id]["callCount"], 1)
            self.assertIn("July 4th/2", by_id[nelson.id]["holidays"])
            # Alex was covered — not credited
            self.assertEqual(by_id[alex.id]["callCount"], 0)
            # Lowest load first among zeros is alphabetical — alex before nelson when both 0?
            # nelson has 1, chris 2, alex 0 → alex first
            self.assertEqual(rows[0]["surgeonId"], alex.id)
        finally:
            db.close()


if __name__ == "__main__":
    unittest.main()
