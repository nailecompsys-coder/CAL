import json
import os
import unittest
from datetime import date

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.admin_metrics_service import build_admin_metrics, default_metrics_range
from app.models import Base, CallCoverage, CallGroup, CallRotation, DayOff, Surgeon


class AdminMetricsServiceTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(bind=self.engine)
        self.Session = sessionmaker(bind=self.engine)

    def tearDown(self):
        Base.metadata.drop_all(bind=self.engine)
        self.engine.dispose()

    def test_day_off_totals_count_pending_approved_half_days_and_exclude_denied(self):
        db = self.Session()
        try:
            chris = self._surgeon("Chris", "Johnson", "physician", 1)
            alex = self._surgeon("Alex", "Schroeder", "physician", 2)
            staff = self._surgeon("Pat", "Staff", "staff", 1)
            db.add_all([chris, alex, staff])
            db.flush()

            db.add(DayOff(
                surgeon_id=chris.id,
                start_date=date(2026, 6, 10),
                end_date=date(2026, 6, 13),
                status="pending",
                is_full_day=False,
                segments=json.dumps([
                    {"date": "2026-06-10", "isFullDay": False, "start": "13:00", "end": "17:00"},
                    {"date": "2026-06-11", "isFullDay": True},
                    {"date": "2026-06-12", "isFullDay": True},
                    {"date": "2026-06-13", "isFullDay": True},
                ]),
            ))
            db.add(DayOff(
                surgeon_id=alex.id,
                start_date=date(2026, 6, 15),
                end_date=date(2026, 6, 15),
                status="approved",
                is_full_day=True,
            ))
            db.add(DayOff(
                surgeon_id=alex.id,
                start_date=date(2026, 6, 16),
                end_date=date(2026, 6, 16),
                status="denied",
                is_full_day=True,
            ))
            db.add(DayOff(
                surgeon_id=staff.id,
                start_date=date(2026, 6, 15),
                end_date=date(2026, 6, 15),
                status="approved",
                is_full_day=True,
            ))
            db.commit()

            metrics = build_admin_metrics(db, date(2026, 1, 1), date(2026, 12, 31), "physician")
            self.assertEqual(metrics["staff_label"], "Surgeons")
            self.assertEqual(metrics["totals"]["requested_days"], 4.5)
            self.assertEqual(metrics["totals"]["approved_days"], 1.0)

            by_initials = {row.surgeon.initials: row for row in metrics["rows"]}
            self.assertEqual(by_initials["CJ"].requested_days, 3.5)
            self.assertEqual(by_initials["CJ"].approved_days, 0.0)
            self.assertEqual(by_initials["AS"].requested_days, 1.0)
            self.assertEqual(by_initials["AS"].approved_days, 1.0)

            staff_metrics = build_admin_metrics(db, date(2026, 1, 1), date(2026, 12, 31), "staff")
            self.assertEqual(staff_metrics["staff_label"], "PAs / Staff")
            self.assertEqual(staff_metrics["totals"]["requested_days"], 1.0)
            self.assertEqual(staff_metrics["totals"]["approved_days"], 1.0)
        finally:
            db.close()

    def test_call_metrics_separate_scheduled_from_taken_and_group_percentages(self):
        db = self.Session()
        try:
            chris = self._surgeon("Chris", "Johnson", "physician", 1)
            alex = self._surgeon("Alex", "Schroeder", "physician", 2)
            lucy = self._surgeon("Lucy", "Woodley", "physician", 3)
            staff = self._surgeon("Pat", "Staff", "staff", 1)
            winter_garden = CallGroup(name="Winter Garden", sort_order=1)
            altamonte = CallGroup(name="Altamonte", sort_order=2)
            db.add_all([chris, alex, lucy, staff, winter_garden, altamonte])
            db.flush()

            covered = CallRotation(call_group_id=winter_garden.id, surgeon_id=chris.id, date=date(2026, 6, 10))
            normal = CallRotation(call_group_id=winter_garden.id, surgeon_id=alex.id, date=date(2026, 6, 11))
            canceled = CallRotation(call_group_id=altamonte.id, surgeon_id=alex.id, date=date(2026, 6, 12))
            staff_call = CallRotation(call_group_id=winter_garden.id, surgeon_id=staff.id, date=date(2026, 6, 13))
            no_call = CallRotation(call_group_id=winter_garden.id, surgeon_id=None, date=date(2026, 6, 14))
            db.add_all([covered, normal, canceled, staff_call, no_call])
            db.flush()

            db.add(CallCoverage(
                call_rotation_id=covered.id,
                original_surgeon_id=chris.id,
                covering_surgeon_id=lucy.id,
                status="active",
            ))
            db.add(CallCoverage(
                call_rotation_id=canceled.id,
                original_surgeon_id=alex.id,
                covering_surgeon_id=lucy.id,
                status="canceled",
            ))
            db.commit()

            metrics = build_admin_metrics(db, date(2026, 1, 1), date(2026, 12, 31), "physician")
            self.assertEqual(metrics["totals"]["scheduled_call_days"], 3)
            self.assertEqual(metrics["totals"]["taken_call_days"], 3)

            by_initials = {row.surgeon.initials: row for row in metrics["rows"]}
            self.assertEqual(by_initials["CJ"].scheduled_call_days, 1)
            self.assertEqual(by_initials["CJ"].taken_call_days, 0)
            self.assertEqual(by_initials["LW"].scheduled_call_days, 0)
            self.assertEqual(by_initials["LW"].taken_call_days, 1)
            self.assertEqual(by_initials["AS"].scheduled_call_days, 2)
            self.assertEqual(by_initials["AS"].taken_call_days, 2)

            winter = next(group for group in metrics["groups"] if group["name"] == "Winter Garden")
            self.assertEqual(winter["scheduled_total"], 2)
            self.assertEqual(winter["taken_total"], 2)
            winter_people = {row["surgeon"].initials: row for row in winter["people"]}
            self.assertEqual(winter_people["CJ"]["scheduled_percent"], 50.0)
            self.assertEqual(winter_people["CJ"]["taken_percent"], 0.0)
            self.assertEqual(winter_people["AS"]["scheduled_percent"], 50.0)
            self.assertEqual(winter_people["AS"]["taken_percent"], 50.0)
            self.assertEqual(winter_people["LW"]["scheduled_percent"], 0.0)
            self.assertEqual(winter_people["LW"]["taken_percent"], 50.0)

            altamonte = next(group for group in metrics["groups"] if group["name"] == "Altamonte")
            altamonte_people = {row["surgeon"].initials: row for row in altamonte["people"]}
            self.assertEqual(altamonte_people["CJ"]["scheduled"], 0)
            self.assertEqual(altamonte_people["CJ"]["taken_percent"], 0.0)

            staff_metrics = build_admin_metrics(db, date(2026, 1, 1), date(2026, 12, 31), "staff")
            self.assertEqual(staff_metrics["totals"]["scheduled_call_days"], 1)
            self.assertEqual(staff_metrics["totals"]["taken_call_days"], 1)
        finally:
            db.close()

    def test_default_metrics_range_is_calendar_year(self):
        start, end = default_metrics_range(date(2026, 6, 17))
        self.assertEqual(start, date(2026, 1, 1))
        self.assertEqual(end, date(2026, 12, 31))

    def _surgeon(self, first_name, last_name, staff_type, sort_order):
        return Surgeon(
            first_name=first_name,
            last_name=last_name,
            email=f"{first_name.lower()}.{last_name.lower()}@example.com",
            staff_type=staff_type,
            sort_order=sort_order,
            is_active=True,
        )


if __name__ == "__main__":
    unittest.main()
