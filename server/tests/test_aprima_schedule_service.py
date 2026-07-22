import os
import unittest
from datetime import date, datetime
from unittest.mock import patch

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("SECRET_KEY", "test-secret")

from app.aprima_schedule_service import (
    APPOINTMENT_SQL,
    MEETING_SQL,
    _local_bounds_for_dates,
    _serialize_row,
    appointment_belongs_to_surgeon,
    fetch_aprima_meetings,
    fetch_main_office_patients_by_weekday,
    is_main_office_site,
    is_surgery_appointment,
    is_surgical_one_dashboard_appointment,
    weekday_range,
)
from app.models import Surgeon


class AprimaScheduleServiceTest(unittest.TestCase):
    def test_weekday_range_is_monday_through_friday(self):
        start, end = weekday_range(date(2026, 7, 9))  # Thursday
        self.assertEqual(start, date(2026, 7, 6))
        self.assertEqual(end, date(2026, 7, 10))

    def test_main_office_site_matching(self):
        self.assertTrue(is_main_office_site("Winter Garden Clinic", ["Winter Garden"]))
        self.assertTrue(is_main_office_site("MFSA Main Office", ["Main Office"]))
        self.assertTrue(is_main_office_site("Clermont Office", ["Clermont Office"]))
        self.assertFalse(is_main_office_site("Advent Lake Mary", ["Winter Garden", "Main Office", "Clermont Office"]))

    def test_surgery_appointment_type_matching(self):
        self.assertTrue(is_surgery_appointment({"appointmentType": "Surgery"}))
        self.assertTrue(is_surgery_appointment({"appointmentType": "surgery"}))
        self.assertFalse(is_surgery_appointment({"appointmentType": "Office Visit"}))
        self.assertFalse(is_surgery_appointment({"appointmentType": "Post Op"}))
        self.assertTrue(
            is_surgical_one_dashboard_appointment(
                {"appointmentType": "Surgery", "serviceSite": "AHWG-Outpt"},
                office_tokens=["Clermont Office"],
            )
        )
        self.assertFalse(
            is_surgical_one_dashboard_appointment(
                {"appointmentType": "Office Visit", "serviceSite": "AHWG-Outpt"},
                office_tokens=["Clermont Office"],
            )
        )

    def test_dashboard_buckets_include_office_and_surgery(self):
        rows = [
            {
                "id": "1",
                "date": "2026-07-06",
                "start": "09:00",
                "end": "09:30",
                "patientName": "Alpha, A",
                "serviceSite": "Winter Garden",
                "surgeonInitials": "JB",
                "surgeonName": "Jorge",
                "appointmentType": "Office Visit",
                "room": "1",
                "mrn": "1",
                "status": "Scheduled",
                "reason": "",
                "timeZone": "America/New_York",
            },
            {
                "id": "2",
                "date": "2026-07-07",
                "start": "10:00",
                "end": "10:30",
                "patientName": "Beta, B",
                "serviceSite": "Lake Mary",
                "surgeonInitials": "AB",
                "surgeonName": "Alex",
                "appointmentType": "Office Visit",
                "room": "2",
                "mrn": "2",
                "status": "Scheduled",
                "reason": "",
                "timeZone": "America/New_York",
            },
            {
                "id": "3",
                "date": "2026-07-08",
                "start": "11:00",
                "end": "11:30",
                "patientName": "Gamma, C",
                "serviceSite": "Main Office",
                "surgeonInitials": "CJ",
                "surgeonName": "Chris",
                "appointmentType": "Office Visit",
                "room": "3",
                "mrn": "3",
                "status": "Scheduled",
                "reason": "",
                "timeZone": "America/New_York",
            },
            {
                "id": "4",
                "date": "2026-07-07",
                "start": "07:30",
                "end": "09:00",
                "patientName": "Delta, D",
                "serviceSite": "AHWG-Outpt",
                "surgeonInitials": "JB",
                "surgeonName": "Jorge",
                "appointmentType": "Surgery",
                "room": "OR 2",
                "mrn": "4",
                "status": "Scheduled",
                "reason": "Hernia",
                "timeZone": "America/New_York",
            },
        ]
        with patch("app.aprima_schedule_service.fetch_patient_appointments", return_value=rows):
            with patch.dict(os.environ, {"APRIMA_MAIN_OFFICE_SITE": "Winter Garden,Main Office"}, clear=False):
                payload = fetch_main_office_patients_by_weekday(date(2026, 7, 9))

        self.assertEqual(payload["total"], 3)
        self.assertEqual(payload["days"][0]["count"], 1)  # Mon office
        self.assertEqual(payload["days"][0]["clinicLabel"], "Winter Garden")
        self.assertEqual(payload["days"][0]["surgeonLabel"], "JB")
        self.assertEqual(payload["days"][1]["count"], 1)  # Tue Surgery @ AHWG (office visit Lake Mary still out)
        self.assertEqual(payload["days"][1]["clinicLabel"], "AHWG-Outpt")
        self.assertEqual(payload["days"][1]["appointments"][0]["appointmentType"], "Surgery")
        self.assertEqual(payload["days"][2]["count"], 1)  # Wed
        self.assertEqual(payload["days"][2]["clinicLabel"], "Main Office")
        self.assertEqual(payload["days"][2]["surgeonLabel"], "CJ")
        self.assertIsNone(payload["warning"])

    def test_dashboard_buckets_filter_main_office_and_group_by_day(self):
        rows = [
            {
                "id": "1",
                "date": "2026-07-06",
                "start": "09:00",
                "end": "09:30",
                "patientName": "Alpha, A",
                "serviceSite": "Winter Garden",
                "surgeonInitials": "JB",
                "surgeonName": "Jorge",
                "appointmentType": "Office Visit",
                "room": "1",
                "mrn": "1",
                "status": "Scheduled",
                "reason": "",
                "timeZone": "America/New_York",
            },
            {
                "id": "2",
                "date": "2026-07-07",
                "start": "10:00",
                "end": "10:30",
                "patientName": "Beta, B",
                "serviceSite": "Lake Mary",
                "surgeonInitials": "AB",
                "surgeonName": "Alex",
                "appointmentType": "Office Visit",
                "room": "2",
                "mrn": "2",
                "status": "Scheduled",
                "reason": "",
                "timeZone": "America/New_York",
            },
            {
                "id": "3",
                "date": "2026-07-08",
                "start": "11:00",
                "end": "11:30",
                "patientName": "Gamma, C",
                "serviceSite": "Main Office",
                "surgeonInitials": "CJ",
                "surgeonName": "Chris",
                "appointmentType": "Office Visit",
                "room": "3",
                "mrn": "3",
                "status": "Scheduled",
                "reason": "",
                "timeZone": "America/New_York",
            },
        ]
        with patch("app.aprima_schedule_service.fetch_patient_appointments", return_value=rows):
            with patch.dict(os.environ, {"APRIMA_MAIN_OFFICE_SITE": "Winter Garden,Main Office"}, clear=False):
                payload = fetch_main_office_patients_by_weekday(date(2026, 7, 9))

        self.assertEqual(payload["total"], 2)
        self.assertEqual(payload["days"][0]["count"], 1)  # Mon
        self.assertEqual(payload["days"][0]["clinicLabel"], "Winter Garden")
        self.assertEqual(payload["days"][0]["surgeonLabel"], "JB")
        self.assertEqual(payload["days"][1]["count"], 0)  # Tue (Lake Mary filtered out)
        self.assertEqual(payload["days"][2]["count"], 1)  # Wed
        self.assertEqual(payload["days"][2]["clinicLabel"], "Main Office")
        self.assertEqual(payload["days"][2]["surgeonLabel"], "CJ")
        self.assertIsNone(payload["warning"])

    def test_aprima_meetings_title_from_reason(self):
        rows = [
            {
                "id": "m1",
                "date": "2026-07-10",
                "start": "12:00",
                "end": "13:00",
                "patientName": "",
                "serviceSite": "Winter Garden",
                "surgeonInitials": "JB",
                "surgeonName": "Jorge Florin",
                "appointmentType": "MEETING",
                "room": "Conf",
                "mrn": "",
                "status": "Scheduled",
                "reason": "Meeting - M&M",
                "timeZone": "America/New_York",
            }
        ]
        with patch("app.aprima_schedule_service._query_rows", return_value=rows):
            payload = fetch_aprima_meetings(date(2026, 7, 9), date(2026, 8, 9))

        self.assertEqual(len(payload["meetings"]), 1)
        self.assertEqual(payload["meetings"][0]["title"], "M&M")
        self.assertEqual(payload["meetings"][0]["source"], "aprima")

    def test_appointment_belongs_to_surgeon_matches_initials_and_name(self):
        surgeon = Surgeon(first_name="Christopher", last_name="Johnson")
        self.assertEqual(surgeon.initials, "CJ")
        self.assertTrue(appointment_belongs_to_surgeon({
            "surgeonInitials": "CJ",
            "surgeonName": "Christopher Johnson",
        }, surgeon))
        self.assertTrue(appointment_belongs_to_surgeon({
            "surgeonInitials": "XX",
            "surgeonName": "Chris Johnson",
        }, surgeon))
        self.assertFalse(appointment_belongs_to_surgeon({
            "surgeonInitials": "AS",
            "surgeonName": "Alexander Schroeder",
        }, surgeon))

    def test_meeting_sql_targets_meeting_type(self):
        self.assertIn("UPPER(COALESCE(lat.Name, '')) = 'MEETING'", MEETING_SQL)
        self.assertIn("a.PatientUid IS NOT NULL", APPOINTMENT_SQL)
        self.assertNotIn("AT TIME ZONE", APPOINTMENT_SQL)

    def test_aprima_query_bounds_use_eastern_dates_as_aprima_utc_datetimes(self):
        start, end = _local_bounds_for_dates(date(2026, 6, 15), date(2026, 6, 21))
        self.assertEqual(start, datetime(2026, 6, 15, 4, 0))
        self.assertEqual(end, datetime(2026, 6, 22, 4, 0))

    def test_aprima_rows_are_serialized_as_eastern_military_time(self):
        row = _serialize_row({
            "appointment_id": "appt-1",
            "aprima_start_datetime": datetime(2026, 6, 15, 12, 20),
            "aprima_end_datetime": datetime(2026, 6, 15, 12, 30),
            "surgeon_initials": "LW",
            "surgeon_name": "Lucille Woodley",
            "patient_name": "Patient, Test",
            "mrn": "123",
            "appointment_type": "Office Visit",
            "status": "Scheduled",
            "reason": "Consult",
            "service_site": "Winter Garden",
            "room": "1",
        })
        self.assertEqual(row["date"], "2026-06-15")
        self.assertEqual(row["start"], "08:20")
        self.assertEqual(row["end"], "08:30")


if __name__ == "__main__":
    unittest.main()
