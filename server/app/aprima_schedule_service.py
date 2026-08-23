"""Read-only Aprima PRM schedule helpers for portal + native views.

CAL never writes to Aprima. Prefer ``aprima_cache_service`` for portal/native
reads (hourly cache). This module remains the live SQL pull used by the worker
and as a fallback when cache is stale/missing.
"""
from __future__ import annotations

import os
import re
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from .models import Surgeon


EASTERN_TZ = ZoneInfo("America/New_York")

# Patient appointments: require a patient, exclude DR OUT / FYI / MEETING.
APPOINTMENT_SQL = """
WITH filtered AS (
  SELECT
    a.AppointmentUid,
    a.StartDateTime,
    a.EndDateTime,
    a.PatientUid,
    a.ProviderUid,
    a.AppointmentTypeUid,
    a.AppointmentStatusUid,
    a.ServiceSiteUid,
    a.RoomUid,
    a.Reason,
    a.StartDateTime AS AprimaStartDateTime,
    a.EndDateTime AS AprimaEndDateTime
  FROM Appointment a
  WHERE a.StartDateTime >= %s
    AND a.StartDateTime < %s
    AND a.StartDateTime IS NOT NULL
    AND a.EndDateTime IS NOT NULL
    AND a.EndDateTime > a.StartDateTime
    AND a.PatientUid IS NOT NULL
    AND a.ProviderUid IS NOT NULL
)
SELECT
  CAST(appt.AppointmentUid AS VARCHAR(36)) AS appointment_id,
  appt.AprimaStartDateTime AS aprima_start_datetime,
  appt.AprimaEndDateTime AS aprima_end_datetime,
  COALESCE(NULLIF(prov.Initials, ''), LEFT(pp.FirstName, 1) + LEFT(pp.LastName, 1)) AS surgeon_initials,
  LTRIM(RTRIM(COALESCE(pp.FirstName, '') + ' ' + COALESCE(pp.LastName, ''))) AS surgeon_name,
  LTRIM(RTRIM(COALESCE(pat.LastName, '') + ', ' + COALESCE(pat.FirstName, ''))) AS patient_name,
  pt.MedicalRecordNumber AS mrn,
  lat.Name AS appointment_type,
  las.Name AS status,
  appt.Reason AS reason,
  lss.Name AS service_site,
  lr.Name AS room
FROM filtered appt
JOIN Patient pt ON pt.PersonUid = appt.PatientUid
JOIN Person pat ON pat.PersonUid = pt.PersonUid
JOIN Provider prov ON prov.PersonUid = appt.ProviderUid
LEFT JOIN Person pp ON pp.PersonUid = prov.PersonUid
LEFT JOIN ListAppointmentType lat ON lat.AppointmentTypeUid = appt.AppointmentTypeUid
LEFT JOIN ListAppointmentStatus las ON las.AppointmentStatusUid = appt.AppointmentStatusUid
LEFT JOIN ListServiceSite lss ON lss.ServiceSiteUid = appt.ServiceSiteUid
LEFT JOIN ListRoom lr ON lr.RoomUid = appt.RoomUid
WHERE (las.IsCanceledStatus = 0 OR las.IsCanceledStatus IS NULL)
  AND las.ShowOnSchedule = 1
  AND (las.Inactive = 0 OR las.Inactive IS NULL)
  AND prov.Inactive = 0
  AND pt.Inactive = 0
  AND (lat.Inactive = 0 OR lat.Inactive IS NULL)
  AND UPPER(COALESCE(las.Name, '')) NOT LIKE '%RECALL%'
  AND UPPER(COALESCE(lat.Name, '')) NOT LIKE '%RECALL%'
  AND UPPER(COALESCE(appt.Reason, '')) NOT LIKE '%RECALL%'
  AND UPPER(COALESCE(lat.Name, '')) NOT IN ('DR OUT', 'FYI', 'MEETING')
  AND UPPER(COALESCE(appt.Reason, '')) NOT LIKE '%POSSIBLE%'
  AND UPPER(COALESCE(appt.Reason, '')) NOT LIKE '%WAITLIST%'
  AND UPPER(COALESCE(appt.Reason, '')) NOT LIKE '%WAIT LIST%'
ORDER BY appt.AprimaStartDateTime, surgeon_name, patient_name
"""

# Aprima calendar meetings: type or reason is MEETING (patient optional).
MEETING_SQL = """
WITH filtered AS (
  SELECT
    a.AppointmentUid,
    a.StartDateTime,
    a.EndDateTime,
    a.PatientUid,
    a.ProviderUid,
    a.AppointmentTypeUid,
    a.AppointmentStatusUid,
    a.ServiceSiteUid,
    a.RoomUid,
    a.Reason,
    a.StartDateTime AS AprimaStartDateTime,
    a.EndDateTime AS AprimaEndDateTime
  FROM Appointment a
  WHERE a.StartDateTime >= %s
    AND a.StartDateTime < %s
    AND a.StartDateTime IS NOT NULL
    AND a.EndDateTime IS NOT NULL
    AND a.EndDateTime > a.StartDateTime
    AND a.ProviderUid IS NOT NULL
)
SELECT
  CAST(appt.AppointmentUid AS VARCHAR(36)) AS appointment_id,
  appt.AprimaStartDateTime AS aprima_start_datetime,
  appt.AprimaEndDateTime AS aprima_end_datetime,
  COALESCE(NULLIF(prov.Initials, ''), LEFT(pp.FirstName, 1) + LEFT(pp.LastName, 1)) AS surgeon_initials,
  LTRIM(RTRIM(COALESCE(pp.FirstName, '') + ' ' + COALESCE(pp.LastName, ''))) AS surgeon_name,
  LTRIM(RTRIM(COALESCE(pat.LastName, '') + ', ' + COALESCE(pat.FirstName, ''))) AS patient_name,
  pt.MedicalRecordNumber AS mrn,
  lat.Name AS appointment_type,
  las.Name AS status,
  appt.Reason AS reason,
  lss.Name AS service_site,
  lr.Name AS room
FROM filtered appt
LEFT JOIN Patient pt ON pt.PersonUid = appt.PatientUid
LEFT JOIN Person pat ON pat.PersonUid = pt.PersonUid
JOIN Provider prov ON prov.PersonUid = appt.ProviderUid
LEFT JOIN Person pp ON pp.PersonUid = prov.PersonUid
LEFT JOIN ListAppointmentType lat ON lat.AppointmentTypeUid = appt.AppointmentTypeUid
LEFT JOIN ListAppointmentStatus las ON las.AppointmentStatusUid = appt.AppointmentStatusUid
LEFT JOIN ListServiceSite lss ON lss.ServiceSiteUid = appt.ServiceSiteUid
LEFT JOIN ListRoom lr ON lr.RoomUid = appt.RoomUid
WHERE (las.IsCanceledStatus = 0 OR las.IsCanceledStatus IS NULL)
  AND las.ShowOnSchedule = 1
  AND (las.Inactive = 0 OR las.Inactive IS NULL)
  AND prov.Inactive = 0
  AND (lat.Inactive = 0 OR lat.Inactive IS NULL)
  AND UPPER(COALESCE(las.Name, '')) NOT LIKE '%RECALL%'
  AND UPPER(COALESCE(lat.Name, '')) NOT LIKE '%RECALL%'
  AND UPPER(COALESCE(appt.Reason, '')) NOT LIKE '%RECALL%'
  AND UPPER(COALESCE(appt.Reason, '')) NOT LIKE '%POSSIBLE%'
  AND UPPER(COALESCE(appt.Reason, '')) NOT LIKE '%WAITLIST%'
  AND UPPER(COALESCE(appt.Reason, '')) NOT LIKE '%WAIT LIST%'
  AND (
    UPPER(COALESCE(lat.Name, '')) = 'MEETING'
    OR UPPER(COALESCE(appt.Reason, '')) LIKE '%MEETING%'
  )
ORDER BY appt.AprimaStartDateTime, surgeon_name
"""


class AprimaScheduleUnavailable(RuntimeError):
    """Raised when Aprima is not configured or the optional driver is missing."""


def main_office_site_tokens() -> list[str]:
    """Service-site name fragments that count as the main office / Surgical One clinic.

    Override with comma-separated APRIMA_MAIN_OFFICE_SITE, e.g.
    ``Winter Garden,Main Office``.
    """
    # Used only to map CBO-style site names onto the "Surgery One" facility label.
    # Surgery One *membership* is not location-gated — see is_surgical_one_dashboard_appointment.
    raw = os.environ.get(
        "APRIMA_MAIN_OFFICE_SITE",
        "Clermont Office,Winter Garden Clinic,Winter Garden,Main Office,Main Clinic",
    ).strip()
    tokens = [part.strip() for part in raw.split(",") if part.strip()]
    return tokens or ["Clermont Office"]


def is_main_office_site(service_site: str, tokens: list[str] | None = None) -> bool:
    site = (service_site or "").strip().lower()
    if not site:
        return False
    for token in tokens or main_office_site_tokens():
        if token.lower() in site:
            return True
    return False


def resolve_aprima_facility_name(service_site: str, *, is_surgery: bool | None = None) -> str:
    """Map Aprima serviceSite onto CAL Clinic / OR schedule facility names.

    Hospital outpatient surgery sites (AHWG-Outpt, …) hang under the matching OR.
    Clermont / main-office IPA patients show as Surgery One on Clinic / OR.
    """
    raw = (service_site or "").strip()
    if not raw:
        return raw
    compact = "".join(ch for ch in raw.upper() if ch.isalnum())
    upper = raw.upper()

    surgery = is_surgery
    if surgery is None:
        surgery = "OUTPT" in upper or compact.startswith("AH")

    # Advent hospital outpatient / OR aliases → CAL hospital locations
    or_aliases = (
        (("AHWG", "WGD", "WINTERGARDENOR"), "Winter Garden OR"),
        (("AHAPOP", "APK", "APOPKAOR"), "Apopka OR"),
        (("AHALT", "ALTAMONTEOR"), "Altamonte OR"),
        (("AHMIN", "MINNEOLAOR"), "Minneola OR"),
        (("AHLM", "LAKEMARYOR"), "Lake Mary OR"),
    )
    for needles, name in or_aliases:
        if any(n in compact for n in needles):
            return name

    # Explicit OR name already in site text
    if "WINTER GARDEN OR" in upper:
        return "Winter Garden OR"
    if "APOPKA OR" in upper:
        return "Apopka OR"

    # Surgery One / IPA / main-office clinic patients
    if is_main_office_site(raw) or not surgery:
        if "APOPKA" in upper and "CLINIC" in upper:
            return "Apopka Clinic"
        if "ALTAMONTE" in upper and "CLINIC" in upper:
            return "Altamonte Clinic"
        if "LAKE MARY" in upper and "CLINIC" in upper:
            return "Lake Mary Clinic"
        if "MINNEOLA" in upper and "CLINIC" in upper:
            return "Minneola Clinic"
        if "WINTER GARDEN CLINIC" in upper:
            return "Winter Garden Clinic"
        # Clermont Office / Main Office / IPA → Surgery One
        return "Surgery One"

    return raw


def surgery_appointment_type_tokens() -> list[str]:
    """Aprima ListAppointmentType names that count as scheduled surgery (not office clinic).

    Override with comma-separated APRIMA_SURGERY_APPOINTMENT_TYPES (default: Surgery).
    Live MFSA types include ``Surgery`` at hospital outpt sites (AHWG-Outpt, AH APOP-Outpt).
    """
    raw = os.environ.get("APRIMA_SURGERY_APPOINTMENT_TYPES", "Surgery").strip()
    tokens = [part.strip() for part in raw.split(",") if part.strip()]
    return tokens or ["Surgery"]


def is_surgery_appointment(row: dict, tokens: list[str] | None = None) -> bool:
    """True when Aprima appointmentType is a surgery booking (not office visit)."""
    typ = (row.get("appointmentType") or "").strip().lower()
    if not typ:
        return False
    for token in tokens or surgery_appointment_type_tokens():
        needle = token.strip().lower()
        if not needle:
            continue
        if typ == needle or needle in typ.split() or typ.startswith(needle):
            return True
    return False


def is_surgical_one_dashboard_appointment(
    row: dict,
    *,
    office_tokens: list[str] | None = None,
    surgery_tokens: list[str] | None = None,
) -> bool:
    """Any harvested Aprima patient appointment is Surgery One.

    Location does not matter (CBO, Lake Mary, HealthPark, hospital outpt, …).
    The patient SQL already excludes DR OUT / FYI / MEETING / waitlist / recall.
    """
    del office_tokens, surgery_tokens
    if not row:
        return False
    return bool(str(row.get("id") or row.get("date") or "").strip())


def monday_of(day: date) -> date:
    return day - timedelta(days=day.weekday())


def weekday_range(anchor: date | None = None) -> tuple[date, date]:
    """Return Mon–Fri for the week containing *anchor* (defaults to today)."""
    start = monday_of(anchor or date.today())
    return start, start + timedelta(days=4)


def native_patient_schedule(
    start_date: date,
    end_date: date,
    surgeon: Surgeon | None = None,
) -> dict:
    """Return Aprima patient appointments for the native Patients tab.

    When *surgeon* is provided, only that surgeon's appointments are returned
    (matched by initials / name against Aprima provider fields).
    """
    rows = fetch_patient_appointments(start_date, end_date)
    if surgeon is not None:
        rows = [row for row in rows if appointment_belongs_to_surgeon(row, surgeon)]
    return {
        "range": {"start": start_date.isoformat(), "end": end_date.isoformat()},
        "appointments": rows,
    }


def appointment_belongs_to_surgeon(row: dict, surgeon: Surgeon) -> bool:
    """Match an Aprima appointment row to a CAL surgeon without PHI leakage."""
    initials = (surgeon.initials or "").strip().upper()
    row_initials = (row.get("surgeonInitials") or "").strip().upper()
    if initials and row_initials and initials == row_initials:
        return True

    full_name = (surgeon.full_name or "").strip().lower()
    row_name = (row.get("surgeonName") or "").strip().lower()
    if full_name and row_name and (full_name == row_name or full_name in row_name or row_name in full_name):
        return True

    # Fallback: last-name token match (handles "Christopher Johnson" vs "Chris Johnson").
    last = (surgeon.last_name or "").strip().lower()
    if last and last in row_name.split():
        first = (surgeon.first_name or "").strip().lower()
        if not first:
            return True
        # Require first initial or first-name token when last name matches.
        if first[0] in {part[:1] for part in row_name.split() if part}:
            return True
        if any(part.startswith(first[:3]) for part in row_name.split() if part):
            return True
    return False


def fetch_patient_appointments(start_date: date, end_date: date) -> list[dict]:
    return _query_rows(APPOINTMENT_SQL, start_date, end_date, kind="patient")


def fetch_main_office_patients_by_weekday(anchor: date | None = None) -> dict:
    """Mon–Fri Surgery One buckets: Aprima patients at any clinic or hospital site."""
    week_start, week_end = weekday_range(anchor)
    tokens = main_office_site_tokens()
    try:
        rows = [
            row
            for row in fetch_patient_appointments(week_start, week_end)
            if is_surgical_one_dashboard_appointment(row, office_tokens=tokens)
        ]
        warning = None
    except AprimaScheduleUnavailable as exc:
        rows = []
        warning = str(exc)
    except Exception as exc:  # noqa: BLE001 — never take down admin dashboard
        rows = []
        warning = f"Aprima temporarily unavailable: {exc}"

    days = []
    for offset in range(5):
        day = week_start + timedelta(days=offset)
        day_key = day.isoformat()
        day_rows = [row for row in rows if row.get("date") == day_key]
        clinics: list[str] = []
        surgeons: list[str] = []
        for row in day_rows:
            site = (row.get("serviceSite") or "").strip()
            if site and site not in clinics:
                clinics.append(site)
            initials = (row.get("surgeonInitials") or "").strip()
            if not initials:
                name = (row.get("surgeonName") or "").strip()
                initials = "".join(part[:1] for part in name.split() if part)[:3]
            if initials and initials not in surgeons:
                surgeons.append(initials)
        days.append({
            "date": day,
            "dateKey": day_key,
            "weekday": day.strftime("%a"),
            "label": day.strftime("%a %-d"),
            "count": len(day_rows),
            "appointments": day_rows,
            "clinics": clinics,
            "surgeons": surgeons,
            "clinicLabel": ", ".join(clinics),
            "surgeonLabel": ", ".join(surgeons),
            "isToday": day == date.today(),
        })

    return {
        "weekStart": week_start,
        "weekEnd": week_end,
        "siteTokens": tokens,
        "days": days,
        "total": len(rows),
        "warning": warning,
    }


def fetch_aprima_meetings(start_date: date, end_date: date) -> dict:
    """Upcoming Aprima MEETING-type appointments for the Meetings screen."""
    try:
        rows = _query_rows(MEETING_SQL, start_date, end_date, kind="meeting")
        warning = None
    except AprimaScheduleUnavailable as exc:
        rows = []
        warning = str(exc)
    except Exception as exc:  # noqa: BLE001 — never take down meetings page
        rows = []
        warning = f"Aprima temporarily unavailable: {exc}"

    meetings = []
    for row in rows:
        title = row.get("reason") or row.get("appointmentType") or "Meeting"
        title = re.sub(r"(?i)^meeting\s*[-:]?\s*", "", title).strip() or "Meeting"
        display_date = row.get("date") or ""
        try:
            display_date = date.fromisoformat(display_date).strftime("%a, %b %-d")
        except ValueError:
            pass
        meetings.append({
            **row,
            "title": title,
            "displayDate": display_date,
            "source": "aprima",
        })

    return {
        "range": {"start": start_date.isoformat(), "end": end_date.isoformat()},
        "meetings": meetings,
        "warning": warning,
    }


def _query_rows(sql: str, start_date: date, end_date: date, *, kind: str) -> list[dict]:
    conn = _connect()
    try:
        with conn.cursor(as_dict=True) as cursor:
            cursor.execute(sql, _local_bounds_for_dates(start_date, end_date))
            rows = [
                row
                for row in (_serialize_row(raw, kind=kind) for raw in cursor.fetchall())
                if start_date.isoformat() <= row["date"] <= end_date.isoformat()
            ]
    finally:
        conn.close()
    return rows


def _connect():
    conn_string = os.environ.get("APRIMA_CONNECTION_STRING", "").strip()
    if not conn_string:
        raise AprimaScheduleUnavailable("Aprima schedule is not configured.")

    try:
        import pymssql
    except ImportError as exc:
        raise AprimaScheduleUnavailable("Aprima SQL driver is not installed.") from exc

    config = _parse_connection_string(conn_string)
    server = config.get("SERVER", "")
    if not server:
        raise AprimaScheduleUnavailable("Aprima server is not configured.")
    if "," in server:
        host, port_text = server.rsplit(",", 1)
        port = int(port_text)
    else:
        host = server
        port = 1433

    return pymssql.connect(
        server=host,
        port=port,
        user=config.get("UID") or config.get("USER"),
        password=config.get("PWD") or config.get("PASSWORD"),
        database=config.get("DATABASE", "PRM"),
        login_timeout=10,
        timeout=30,
    )


def _parse_connection_string(conn_string: str) -> dict[str, str]:
    config: dict[str, str] = {}
    for part in conn_string.split(";"):
        if "=" not in part:
            continue
        key, value = part.split("=", 1)
        config[key.strip().upper()] = value.strip()
    return config


def _local_bounds_for_dates(start_date: date, end_date: date) -> tuple[datetime, datetime]:
    """Return Aprima UTC datetime bounds for Eastern calendar dates."""
    local_start = datetime.combine(start_date, time.min, tzinfo=EASTERN_TZ)
    local_end = datetime.combine(end_date + timedelta(days=1), time.min, tzinfo=EASTERN_TZ)
    return (
        local_start.astimezone(timezone.utc).replace(tzinfo=None),
        local_end.astimezone(timezone.utc).replace(tzinfo=None),
    )


def _serialize_row(row: dict, *, kind: str = "patient") -> dict:
    local_start = _eastern_from_aprima_utc(row.get("aprima_start_datetime"))
    local_end = _eastern_from_aprima_utc(row.get("aprima_end_datetime"))
    patient_name = (row.get("patient_name") or "").strip()
    if kind == "meeting" and (not patient_name or patient_name == ","):
        patient_name = ""

    return {
        "id": row.get("appointment_id"),
        "date": local_start.date().isoformat() if local_start else "",
        "start": _format_hhmm(local_start),
        "end": _format_hhmm(local_end),
        "timeZone": "America/New_York",
        "surgeonInitials": (row.get("surgeon_initials") or "").strip(),
        "surgeonName": (row.get("surgeon_name") or "Unassigned").strip(),
        "patientName": patient_name,
        "mrn": (row.get("mrn") or "").strip() if kind == "patient" else "",
        "appointmentType": (row.get("appointment_type") or "").strip(),
        "status": (row.get("status") or "").strip(),
        "reason": (row.get("reason") or "").strip(),
        "serviceSite": (row.get("service_site") or "").strip(),
        "room": (row.get("room") or "").strip(),
    }


def _eastern_from_aprima_utc(value) -> datetime | None:
    if not isinstance(value, datetime):
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(EASTERN_TZ)


def _format_hhmm(value: datetime | None) -> str:
    return value.strftime("%H:%M") if value else ""
