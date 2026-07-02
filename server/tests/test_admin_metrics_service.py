import json
import os
import unittest
from datetime import date

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.admin_metrics_service import approved_day_off_detail, build_admin_metrics, default_metrics_range
from app.models import Base, CallCoverage, CallGroup, CallRotation, DayOff, Surgeon


class AdminMetricsServiceTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(bind=self.engine)
        self.Session = sessionmaker(bind=self.engine)

    def tearDown(self):
        Base.metadata.drop_all(bind=self.engine)
        self.engine.dispose()

    def test_day_off_metrics_split_approved_taken_and_upcoming_for_all_roles(self):
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
                status="approved",
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
                start_date=date(2026, 6, 18),
                end_date=date(2026, 6, 18),
                status="approved",
                is_full_day=True,
            ))
            db.add(DayOff(
                surgeon_id=alex.id,
                start_date=date(2026, 6, 19),
                end_date=date(2026, 6, 19),
                status="pending",
                is_full_day=True,
            ))
            db.add(DayOff(
                surgeon_id=alex.id,
                start_date=date(2026, 6, 20),
                end_date=date(2026, 6, 20),
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

            metrics = build_admin_metrics(db, date(2026, 1, 1), date(2026, 12, 31), "all", today=date(2026, 6, 17))
            self.assertEqual(metrics["staff_label"], "Surgeons and PAs / Staff")
            self.assertEqual(metrics["totals"]["day_off_taken"], 4.5)
            self.assertEqual(metrics["totals"]["day_off_approved_upcoming"], 1.0)

            by_initials = {row.surgeon.initials: row for row in metrics["rows"]}
            self.assertEqual(by_initials["CJ"].day_off_taken, 3.5)
            self.assertEqual(by_initials["CJ"].day_off_approved_upcoming, 0.0)
            self.assertEqual(by_initials["CJ"].days_off_approved, 3.5)
            self.assertEqual(by_initials["CJ"].days_off_percent, 77.8)
            self.assertEqual(by_initials["AS"].day_off_taken, 0.0)
            self.assertEqual(by_initials["AS"].day_off_approved_upcoming, 1.0)
            self.assertEqual(by_initials["AS"].days_off_approved, 1.0)
            self.assertEqual(by_initials["AS"].days_off_percent, 22.2)
            self.assertEqual(by_initials["PS"].day_off_taken, 1.0)
            self.assertEqual(by_initials["PS"].day_off_approved_upcoming, 0.0)
            self.assertEqual(by_initials["PS"].days_off_approved, 1.0)
            self.assertEqual(by_initials["PS"].days_off_percent, 100.0)

            detail = approved_day_off_detail(db, chris.id, date(2026, 1, 1), date(2026, 12, 31), today=date(2026, 6, 17))
            self.assertEqual(detail["surgeon"].initials, "CJ")
            self.assertEqual(detail["taken_total"], 3.5)
            self.assertEqual(detail["approved_upcoming_total"], 0.0)
            self.assertEqual(len(detail["segments"]), 4)
            self.assertEqual(detail["segments"][0]["label"], "13:00-17:00")
        finally:
            db.close()

    def test_call_metrics_split_taken_and_upcoming_with_role_specific_percentages(self):
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
            past_normal = CallRotation(call_group_id=winter_garden.id, surgeon_id=alex.id, date=date(2026, 6, 11))
            future_normal = CallRotation(call_group_id=winter_garden.id, surgeon_id=alex.id, date=date(2026, 6, 18))
            future_covered = CallRotation(call_group_id=altamonte.id, surgeon_id=alex.id, date=date(2026, 6, 19))
            staff_call = CallRotation(call_group_id=winter_garden.id, surgeon_id=staff.id, date=date(2026, 6, 18))
            no_call = CallRotation(call_group_id=winter_garden.id, surgeon_id=None, date=date(2026, 6, 14))
            db.add_all([covered, past_normal, future_normal, future_covered, staff_call, no_call])
            db.flush()

            db.add(CallCoverage(
                call_rotation_id=covered.id,
                original_surgeon_id=chris.id,
                covering_surgeon_id=lucy.id,
                status="active",
            ))
            db.add(CallCoverage(
                call_rotation_id=future_covered.id,
                original_surgeon_id=alex.id,
                covering_surgeon_id=lucy.id,
                status="active",
            ))
            db.commit()

            metrics = build_admin_metrics(db, date(2026, 1, 1), date(2026, 12, 31), "all", today=date(2026, 6, 17))
            self.assertEqual(metrics["totals"]["call_taken"], 2)
            self.assertEqual(metrics["totals"]["call_scheduled_upcoming"], 3)

            by_initials = {row.surgeon.initials: row for row in metrics["rows"]}
            self.assertEqual(by_initials["CJ"].call_taken, 0)
            self.assertEqual(by_initials["CJ"].call_scheduled_upcoming, 0)
            self.assertEqual(by_initials["CJ"].total_call_scheduled, 0)
            self.assertEqual(by_initials["CJ"].total_call_percent, 0.0)
            self.assertEqual(by_initials["LW"].call_taken, 1)
            self.assertEqual(by_initials["LW"].call_scheduled_upcoming, 1)
            self.assertEqual(by_initials["LW"].total_call_scheduled, 2)
            self.assertEqual(by_initials["LW"].total_call_percent, 50.0)
            self.assertEqual(by_initials["AS"].call_taken, 1)
            self.assertEqual(by_initials["AS"].call_scheduled_upcoming, 1)
            self.assertEqual(by_initials["AS"].total_call_scheduled, 2)
            self.assertEqual(by_initials["AS"].total_call_percent, 50.0)
            self.assertEqual(by_initials["PS"].call_taken, 0)
            self.assertEqual(by_initials["PS"].call_scheduled_upcoming, 1)
            self.assertEqual(by_initials["PS"].total_call_scheduled, 1)
            self.assertEqual(by_initials["PS"].total_call_percent, 100.0)

            winter = next(group for group in metrics["groups"] if group["name"] == "Winter Garden")
            self.assertEqual(winter["scheduled_total"], 2)
            self.assertEqual(winter["taken_total"], 2)
            winter_people = {row["surgeon"].initials: row for row in winter["people"]}
            self.assertEqual(winter_people["CJ"]["scheduled_percent"], 0.0)
            self.assertEqual(winter_people["CJ"]["taken_percent"], 0.0)
            self.assertEqual(winter_people["AS"]["scheduled_percent"], 100.0)
            self.assertEqual(winter_people["AS"]["taken_percent"], 50.0)
            self.assertEqual(winter_people["LW"]["scheduled_percent"], 0.0)
            self.assertEqual(winter_people["LW"]["taken_percent"], 50.0)
            self.assertEqual(winter_people["PS"]["scheduled_percent"], 100.0)

            altamonte = next(group for group in metrics["groups"] if group["name"] == "Altamonte")
            altamonte_people = {row["surgeon"].initials: row for row in altamonte["people"]}
            self.assertEqual(altamonte_people["CJ"]["scheduled"], 0)
            self.assertEqual(altamonte_people["CJ"]["taken_percent"], 0.0)
            self.assertEqual(altamonte_people["LW"]["scheduled"], 1)
            self.assertEqual(altamonte_people["LW"]["scheduled_percent"], 100.0)
        finally:
            db.close()

    def test_default_metrics_range_is_calendar_year(self):
        start, end = default_metrics_range(date(2026, 6, 17))
        self.assertEqual(start, date(2026, 1, 1))
        self.assertEqual(end, date(2026, 12, 31))

    def test_metrics_excludes_developer_admin_from_rows_totals_and_detail(self):
        db = self.Session()
        try:
            chris = self._surgeon("Chris", "Johnson", "physician", 1)
            hidden = self._surgeon("Developer", "Admin", "physician", 999)
            hidden.email = "don@clermontitstore.com"
            group = CallGroup(name="Winter Garden", sort_order=1)
            db.add_all([chris, hidden, group])
            db.flush()

            db.add(DayOff(
                surgeon_id=hidden.id,
                start_date=date(2026, 6, 10),
                end_date=date(2026, 6, 10),
                status="approved",
                is_full_day=True,
            ))
            db.add(CallRotation(
                call_group_id=group.id,
                surgeon_id=hidden.id,
                date=date(2026, 6, 10),
            ))
            db.add(CallRotation(
                call_group_id=group.id,
                surgeon_id=chris.id,
                date=date(2026, 6, 11),
            ))
            db.commit()

            metrics = build_admin_metrics(db, date(2026, 1, 1), date(2026, 12, 31), "all", today=date(2026, 6, 17))
            self.assertEqual([row.surgeon.initials for row in metrics["rows"]], ["CJ"])
            self.assertEqual(metrics["totals"]["day_off_taken"], 0.0)
            self.assertEqual(metrics["totals"]["call_taken"], 1)
            self.assertIsNone(approved_day_off_detail(db, hidden.id, date(2026, 1, 1), date(2026, 12, 31), today=date(2026, 6, 17)))
        finally:
            db.close()

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
