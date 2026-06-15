"""Read-only Aprima schedule feed for the native patient view."""
from __future__ import annotations

import os
from datetime import date


APPOINTMENT_SQL = """
SELECT
  CAST(a.AppointmentUid AS VARCHAR(36)) AS appointment_id,
  CAST(a.StartDateTime AS DATE) AS appointment_date,
  CONVERT(VARCHAR(5), a.StartDateTime, 108) AS start_time,
  CONVERT(VARCHAR(5), a.EndDateTime, 108) AS end_time,
  COALESCE(NULLIF(prov.Initials, ''), LEFT(pp.FirstName, 1) + LEFT(pp.LastName, 1)) AS surgeon_initials,
  LTRIM(RTRIM(COALESCE(pp.FirstName, '') + ' ' + COALESCE(pp.LastName, ''))) AS surgeon_name,
  LTRIM(RTRIM(COALESCE(pat.LastName, '') + ', ' + COALESCE(pat.FirstName, ''))) AS patient_name,
  pt.MedicalRecordNumber AS mrn,
  lat.Name AS appointment_type,
  las.Name AS status,
  a.Reason AS reason,
  lss.Name AS service_site,
  lr.Name AS room
FROM Appointment a
JOIN Patient pt ON pt.PersonUid = a.PatientUid
JOIN Person pat ON pat.PersonUid = pt.PersonUid
LEFT JOIN Provider prov ON prov.PersonUid = a.ProviderUid
LEFT JOIN Person pp ON pp.PersonUid = prov.PersonUid
LEFT JOIN ListAppointmentType lat ON lat.AppointmentTypeUid = a.AppointmentTypeUid
LEFT JOIN ListAppointmentStatus las ON las.AppointmentStatusUid = a.AppointmentStatusUid
LEFT JOIN ListServiceSite lss ON lss.ServiceSiteUid = a.ServiceSiteUid
LEFT JOIN ListRoom lr ON lr.RoomUid = a.RoomUid
WHERE a.StartDateTime >= %s
  AND a.StartDateTime < DATEADD(day, 1, %s)
  AND (las.IsCanceledStatus = 0 OR las.IsCanceledStatus IS NULL)
  AND (prov.Inactive = 0 OR prov.Inactive IS NULL)
ORDER BY CAST(a.StartDateTime AS DATE), surgeon_name, a.StartDateTime, patient_name
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
            cursor.execute(APPOINTMENT_SQL, (start_date.isoformat(), end_date.isoformat()))
            rows = [_serialize_row(row) for row in cursor.fetchall()]
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


def _serialize_row(row: dict) -> dict:
    appointment_date = row.get("appointment_date")
    if hasattr(appointment_date, "isoformat"):
        appointment_date = appointment_date.isoformat()

    return {
        "id": row.get("appointment_id"),
        "date": appointment_date,
        "start": row.get("start_time") or "",
        "end": row.get("end_time") or "",
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
