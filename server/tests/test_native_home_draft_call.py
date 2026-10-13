import os
import unittest
from datetime import date

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models import Base, CallDraftAssignment, CallGroup, CallRotation, Surgeon
from app.native_home_service import build_native_home


class NativeHomeDraftCallTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(bind=self.engine)
        self.Session = sessionmaker(bind=self.engine)

    def tearDown(self):
        Base.metadata.drop_all(bind=self.engine)
        self.engine.dispose()

    def test_native_home_overlays_draft_call_far_out(self):
        """Built Call Builder drafts appear in Calendar Call for the requested month."""
        db = self.Session()
        try:
            viewer = Surgeon(
                first_name="Don",
                last_name="Admin",
                email="don@example.com",
                staff_type="physician",
                sort_order=1,
                is_active=True,
            )
            chris = Surgeon(
                first_name="Chris",
                last_name="Johnson",
                email="chris@example.com",
                staff_type="physician",
                sort_order=2,
                is_active=True,
            )
            alex = Surgeon(
                first_name="Alex",
                last_name="Schroeder",
                email="alex@example.com",
                staff_type="physician",
                sort_order=3,
                is_active=True,
            )
            wg = CallGroup(name="Winter Garden", sort_order=1)
            alt = CallGroup(name="Altamonte", sort_order=2)
            db.add_all([viewer, chris, alex, wg, alt])
            db.flush()

            # Live only through November.
            db.add(
                CallRotation(
                    call_group_id=wg.id,
                    surgeon_id=chris.id,
                    date=date(2026, 11, 30),
                )
            )
            # CJ built December + a year-ahead cell in draft only.
            db.add_all([
                CallDraftAssignment(
                    date=date(2026, 12, 15),
                    call_group_id=wg.id,
                    surgeon_id=alex.id,
                ),
                CallDraftAssignment(
                    date=date(2027, 10, 9),
                    call_group_id=alt.id,
                    surgeon_id=chris.id,
                ),
            ])
            db.commit()

            december = build_native_home(db, viewer, date(2026, 12, 1), date(2026, 12, 31))
            dec_15 = next(day for day in december["days"] if day["date"] == "2026-12-15")
            self.assertEqual(len(dec_15["callAssignments"]), 1)
            self.assertEqual(dec_15["callAssignments"][0]["initials"], "AS")
            self.assertEqual(dec_15["callAssignments"][0]["source"], "draft")
            # 0 keeps older Int-only iOS clients decoding; cover treats 0 as non-live.
            self.assertEqual(dec_15["callAssignments"][0]["rotationId"], 0)

            far = build_native_home(db, viewer, date(2027, 10, 1), date(2027, 10, 31))
            oct_9 = next(day for day in far["days"] if day["date"] == "2027-10-09")
            self.assertEqual(oct_9["callAssignments"][0]["initials"], "CJ")
            self.assertEqual(oct_9["callAssignments"][0]["group"], "Altamonte")

            # Draft wins over live on the same cell.
            db.add(
                CallDraftAssignment(
                    date=date(2026, 11, 30),
                    call_group_id=wg.id,
                    surgeon_id=alex.id,
                )
            )
            db.commit()
            november = build_native_home(db, viewer, date(2026, 11, 30), date(2026, 11, 30))
            self.assertEqual(november["days"][0]["callAssignments"][0]["initials"], "AS")
            self.assertEqual(november["days"][0]["callAssignments"][0]["source"], "draft")
        finally:
            db.close()


if __name__ == "__main__":
    unittest.main()
