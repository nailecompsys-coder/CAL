"""Read-only Aprima schedule feed for the native patient view."""
from __future__ import annotations

import os
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo


EASTERN_TZ = ZoneInfo("America/New_York")


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


class AprimaScheduleUnavailable(RuntimeError):
    """Raised when Aprima is not configured or the optional driver is missing."""


def native_patient_schedule(start_date: date, end_date: date) -> dict:
    """Return the Aprima appointment list grouped for native CAL.

    The CAL database remains the system of record for schedule/call data. This
    function only reads Aprima PRM through a separate read-only connection.
    """

    conn = _connect()
    try:
        with conn.cursor(as_dict=True) as cursor:
            cursor.execute(APPOINTMENT_SQL, _local_bounds_for_dates(start_date, end_date))
            rows = [
                row
                for row in (_serialize_row(row) for row in cursor.fetchall())
                if start_date.isoformat() <= row["date"] <= end_date.isoformat()
            ]
    finally:
        conn.close()

    return {
        "range": {"start": start_date.isoformat(), "end": end_date.isoformat()},
        "appointments": rows,
    }


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


def _serialize_row(row: dict) -> dict:
    local_start = _eastern_from_aprima_utc(row.get("aprima_start_datetime"))
    local_end = _eastern_from_aprima_utc(row.get("aprima_end_datetime"))

    return {
        "id": row.get("appointment_id"),
        "date": local_start.date().isoformat() if local_start else "",
        "start": _format_hhmm(local_start),
        "end": _format_hhmm(local_end),
        "timeZone": "America/New_York",
        "surgeonInitials": (row.get("surgeon_initials") or "").strip(),
        "surgeonName": (row.get("surgeon_name") or "Unassigned").strip(),
        "patientName": (row.get("patient_name") or "").strip(),
        "mrn": (row.get("mrn") or "").strip(),
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
