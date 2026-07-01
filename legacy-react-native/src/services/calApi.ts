import { API_BASE_URL } from "../config/env";
import type {
  CalEvent,
  DayItemResponse,
  NativeHome,
  NativeCallCoverageResponse,
  NativeDayOffRequest,
  NativeRequestOffResponse,
  NativePatientScheduleResponse,
  NativeSaveResponse,
  OtpRequestResponse,
  OtpVerifyResponse,
} from "../types/cal";

/** Set from App on mount: clear local session when the server rejects the device JWT (401). */
let unauthorizedHandler: (() => void) | null = null;

export function setCalApiUnauthorizedHandler(handler: (() => void) | null): void {
  unauthorizedHandler = handler;
}

function notifySessionInvalid(path: string, status: number): void {
  if (status !== 401 || path.includes("/surgeon/otp/") || !unauthorizedHandler) return;
  try {
    unauthorizedHandler();
  } catch {
    // ignore
  }
}

function formatFetchError(url: string, err: unknown): string {
  if (err instanceof Error && err.message) return err.message;
  if (typeof err === "object" && err !== null && "message" in err) {
    return String((err as { message: unknown }).message);
  }
  return String(err);
}

async function apiCall<T>(
  path: string,
  opts: RequestInit = {},
  token?: string
): Promise<T> {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(opts.headers as Record<string, string>),
  };
  if (token) {
    const t = token.trim();
    if (t) {
      headers.Authorization = `Bearer ${t}`;
      headers["X-CAL-Device-Token"] = t;
    }
  }

  const url = `${API_BASE_URL}${path}`;
  let res: Response;
  try {
    res = await fetch(url, { ...opts, headers });
  } catch (err) {
    throw new Error(
      `Network: ${formatFetchError(url, err)} (url=${url})`
    );
  }
  if (!res.ok) {
    const body = await res.text();
    notifySessionInvalid(path, res.status);
    if (res.status === 401 && !path.includes("/surgeon/otp/")) {
      throw new Error("Session expired or device was signed out. Please log in again.");
    }
    throw new Error(`HTTP ${res.status}: ${body || res.statusText} (url=${url})`);
  }
  return res.json() as Promise<T>;
}

function isoDay(offset: number): string {
  const d = new Date();
  d.setDate(d.getDate() + offset);
  return d.toISOString().slice(0, 10);
}

export function requestOtp(email: string): Promise<OtpRequestResponse> {
  return apiCall<OtpRequestResponse>("/api/surgeon/otp/request", {
    method: "POST",
    body: JSON.stringify({ email: email.trim() }),
  });
}

export function verifyOtp(email: string, code: string): Promise<OtpVerifyResponse> {
  return apiCall<OtpVerifyResponse>("/api/surgeon/otp/verify", {
    method: "POST",
    body: JSON.stringify({ email: email.trim(), code: code.trim() }),
  });
}

export function fetchMyEvents(token: string): Promise<CalEvent[]> {
  const start = isoDay(-2);
  const end = isoDay(10);
  return apiCall<CalEvent[]>(
    `/api/my-events?start=${encodeURIComponent(start)}&end=${encodeURIComponent(end)}`,
    { method: "GET" },
    token
  );
}

export function fetchNativeHome(token: string, weekOffset = 0, daysAhead = 365): Promise<NativeHome> {
  const today = new Date();
  const monday = new Date(today);
  monday.setDate(today.getDate() - ((today.getDay() + 6) % 7) + weekOffset * 7);
  const sunday = new Date(monday);
  sunday.setDate(monday.getDate() + daysAhead);
  const start = monday.toISOString().slice(0, 10);
  const end = sunday.toISOString().slice(0, 10);
  return apiCall<NativeHome>(
    `/api/native/home?start=${encodeURIComponent(start)}&end=${encodeURIComponent(end)}`,
    { method: "GET" },
    token
  );
}

export function fetchPatientSchedule(
  token: string,
  start: string,
  end: string
): Promise<NativePatientScheduleResponse> {
  return apiCall<NativePatientScheduleResponse>(
    `/api/native/patient-schedule?start=${encodeURIComponent(start)}&end=${encodeURIComponent(end)}`,
    { method: "GET" },
    token
  );
}

export function submitRequestOff(
  token: string,
  startDate: string,
  endDate: string,
  reason: string,
  notes: string,
  isFullDay = true,
  start?: string | null,
  end?: string | null,
  segments?: NativeDayOffRequest["segments"]
): Promise<NativeRequestOffResponse> {
  return apiCall<NativeRequestOffResponse>(
    "/api/native/request-off",
    {
      method: "POST",
      body: JSON.stringify({
        start_date: startDate,
        end_date: endDate,
        reason,
        notes,
        is_full_day: isFullDay,
        start,
        end,
        segments,
      }),
    },
    token
  );
}

export function updateRequestOff(
  token: string,
  requestId: number,
  startDate: string,
  endDate: string,
  reason: string,
  notes: string,
  isFullDay = true,
  start?: string | null,
  end?: string | null,
  segments?: NativeDayOffRequest["segments"]
): Promise<NativeRequestOffResponse> {
  return apiCall<NativeRequestOffResponse>(
    `/api/native/request-off/${requestId}`,
    {
      method: "PUT",
      body: JSON.stringify({
        start_date: startDate,
        end_date: endDate,
        reason,
        notes,
        is_full_day: isFullDay,
        start,
        end,
        segments,
      }),
    },
    token
  );
}

export function cancelRequestOff(token: string, requestId: number): Promise<{ ok: boolean }> {
  return apiCall<{ ok: boolean }>(
    `/api/native/request-off/${requestId}`,
    { method: "DELETE" },
    token
  );
}

export function submitCallCoverage(
  token: string,
  rotationId: number,
  coveringSurgeonId?: number,
  notes = ""
): Promise<NativeCallCoverageResponse> {
  return apiCall<NativeCallCoverageResponse>(
    "/api/native/call-coverage",
    {
      method: "POST",
      body: JSON.stringify({
        rotation_id: rotationId,
        covering_surgeon_id: coveringSurgeonId,
        notes,
      }),
    },
    token
  );
}

export function saveSurgeryNotes(
  token: string,
  caseId: number,
  notes: string
): Promise<NativeSaveResponse> {
  return apiCall<NativeSaveResponse>(
    `/api/native/surgical-case/${caseId}/notes`,
    {
      method: "POST",
      body: JSON.stringify({ notes }),
    },
    token
  );
}

export function registerNativePushToken(token: string, pushToken: string, platform = "ios"): Promise<NativeSaveResponse> {
  return apiCall<NativeSaveResponse>(
    "/api/native/push-token",
    {
      method: "POST",
      body: JSON.stringify({ token: pushToken, platform }),
    },
    token
  );
}

export function markNativeAlertsRead(token: string): Promise<{ ok: boolean; count: number }> {
  return apiCall<{ ok: boolean; count: number }>(
    "/api/native/alerts/read",
    { method: "POST" },
    token
  );
}

export function createDayItem(
  token: string,
  date: string,
  title: string,
  notes = "",
  start?: string | null,
  end?: string | null
): Promise<DayItemResponse> {
  return apiCall<DayItemResponse>(
    "/surgeon/api/day-items",
    {
      method: "POST",
      body: JSON.stringify({
        date,
        title: title.trim(),
        notes,
        start_time: start || null,
        end_time: end || null,
      }),
    },
    token
  );
}

export function updateDayItem(
  token: string,
  id: number,
  title: string,
  notes = "",
  start?: string | null,
  end?: string | null
): Promise<DayItemResponse> {
  return apiCall<DayItemResponse>(
    `/surgeon/api/day-items/${id}`,
    {
      method: "PATCH",
      body: JSON.stringify({
        title: title.trim(),
        notes,
        start_time: start || null,
        end_time: end || null,
      }),
    },
    token
  );
}

export async function deleteDayItem(token: string, id: number): Promise<void> {
  const path = `/surgeon/api/day-items/${id}`;
  const url = `${API_BASE_URL}${path}`;
  const t = token.trim();
  if (!t) {
    throw new Error(`HTTP 401: missing token (url=${url})`);
  }
  const headers: Record<string, string> = {
    Authorization: `Bearer ${t}`,
    "X-CAL-Device-Token": t,
  };
  let res: Response;
  try {
    res = await fetch(url, { method: "DELETE", headers });
  } catch (err) {
    throw new Error(`Network: ${formatFetchError(url, err)} (url=${url})`);
  }
  if (!res.ok) {
    const body = await res.text();
    notifySessionInvalid(path, res.status);
    throw new Error(`HTTP ${res.status}: ${body || res.statusText} (url=${url})`);
  }
}
