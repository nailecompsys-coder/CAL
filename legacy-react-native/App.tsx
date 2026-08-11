import { StatusBar } from 'expo-status-bar';
import Constants from 'expo-constants';
import * as Device from 'expo-device';
import * as Notifications from 'expo-notifications';
import { useEffect, useMemo, useState } from 'react';
import { Platform, StyleSheet, View } from 'react-native';
import { API_BASE_URL } from './src/config/env';
import { AuthScreen } from './src/features/auth/AuthScreen';
import { ScheduleScreen } from './src/features/schedule/ScheduleScreen';
import { clearToken, readToken, saveToken } from './src/auth/tokenStore';
import {
  cancelRequestOff,
  createDayItem,
  deleteDayItem,
  fetchNativeHome,
  fetchPatientSchedule,
  markNativeAlertsRead,
  registerNativePushToken,
  requestOtp,
  setCalApiUnauthorizedHandler,
  submitCallCoverage,
  submitRequestOff,
  updateDayItem,
  updateRequestOff,
  verifyOtp,
} from './src/services/calApi';
import type { NativeDayOffRequest, NativeHome, PatientAppointment } from './src/types/cal';

type TabKey = 'schedule' | 'request' | 'patients';

export default function App() {
  const [email, setEmail] = useState('');
  const [code, setCode] = useState('');
  const [token, setToken] = useState('');
  const [busy, setBusy] = useState(false);
  const [home, setHome] = useState<NativeHome | null>(null);
  const [patientAppointments, setPatientAppointments] = useState<PatientAppointment[]>([]);
  const [patientWarning, setPatientWarning] = useState('');
  const [activeTab, setActiveTab] = useState<TabKey>('schedule');
  const [weekOffset, setWeekOffset] = useState(0);
  const [requestDraft, setRequestDraft] = useState({
    startDate: new Date().toISOString().slice(0, 10),
    endDate: new Date().toISOString().slice(0, 10),
    reason: '',
    notes: '',
    isFullDay: true,
    start: '07:00',
    end: '11:00',
    segments: [] as NonNullable<NativeDayOffRequest['segments']>,
  });
  const [lastSync, setLastSync] = useState<string>('');
  const [message, setMessage] = useState('Enter your CAL surgeon email to request an OTP.');

  const isAuthed = useMemo(() => token.length > 0, [token]);

  useEffect(() => {
    setCalApiUnauthorizedHandler(() => {
      void clearToken();
      setToken('');
      setHome(null);
      setWeekOffset(0);
      setMessage('Session expired or device was signed out. Log in again.');
    });
    return () => setCalApiUnauthorizedHandler(null);
  }, []);

  useEffect(() => {
    (async () => {
      const saved = await readToken();
      if (!saved) return;
      setToken(saved);
      setMessage('Restored session. Loading CAL...');
      await loadHome(saved, 0);
    })();
  }, []);

  // Refresh schedule whenever a push notification arrives.
  useEffect(() => {
    if (!token) return;
    // Foreground: notification received while app is open
    const foregroundSub = Notifications.addNotificationReceivedListener(() => {
      loadHome(token, weekOffset);
    });
    // Background/quit: user taps a notification to open the app
    const responseSub = Notifications.addNotificationResponseReceivedListener(() => {
      loadHome(token, weekOffset);
    });
    return () => {
      foregroundSub.remove();
      responseSub.remove();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token, weekOffset]);

  async function onRequestOtp() {
    setBusy(true);
    setMessage('');
    try {
      const data = await requestOtp(email);
      if (data.ok === false || data.sent === false) {
        setMessage(data.message || 'Could not send a code. Try again or contact the office.');
      } else if (data.devCode) {
        setMessage(`Local access code: ${data.devCode}`);
      } else {
        setMessage(data.message ?? 'Check your email or iPhone for the CAL access code.');
      }
    } catch (err) {
      const detail = err instanceof Error ? err.message : 'request error';
      setMessage(`OTP request failed (${API_BASE_URL}): ${detail}`);
    } finally {
      setBusy(false);
    }
  }

  async function onVerifyOtp() {
    setBusy(true);
    setMessage('');
    try {
      const data = await verifyOtp(email, code);
      const jwt = (data.token ?? "").trim();
      if (!jwt) {
        setMessage("Login failed: server did not return a session token.");
        return;
      }
      setToken(jwt);
      await saveToken(jwt);
      setMessage("Login successful. Loading CAL...");
      await loadHome(jwt, weekOffset);
    } catch (err) {
      setMessage(err instanceof Error ? err.message : 'OTP verify failed');
    } finally {
      setBusy(false);
    }
  }

  async function onLogout() {
    await clearToken();
    setToken('');
    setHome(null);
    setWeekOffset(0);
    setCode('');
    setMessage('Logged out.');
  }

  async function loadHome(sessionToken: string = token, nextWeekOffset = weekOffset) {
    const tok = sessionToken.trim();
    if (!tok) {
      setMessage('Log in first.');
      return;
    }
    setBusy(true);
    setMessage('');
    try {
      const data = await fetchNativeHome(tok, nextWeekOffset);
      setHome(data);
      await registerForNativePush(tok);
      setLastSync(new Date().toLocaleTimeString());
      setMessage('');
      if (activeTab === 'patients') {
        await loadPatients(tok, data.range);
      }
    } catch (err) {
      setMessage(err instanceof Error ? err.message : 'CAL load failed');
    } finally {
      setBusy(false);
    }
  }

  async function loadPatients(
    sessionToken: string = token,
    range: NativeHome['range'] | null = home?.range ?? null
  ) {
    const tok = sessionToken.trim();
    if (!tok) {
      setMessage('Log in first.');
      return;
    }
    const activeRange = range ?? defaultPatientRange();
    setBusy(true);
    setPatientWarning('');
    try {
      const data = await fetchPatientSchedule(tok, activeRange.start, activeRange.end);
      setPatientAppointments(data.appointments ?? []);
      setPatientWarning(data.warning ?? '');
      setMessage('');
    } catch (err) {
      const detail = err instanceof Error ? err.message : 'Aprima schedule failed';
      setPatientAppointments([]);
      setPatientWarning(detail);
      setMessage(detail);
    } finally {
      setBusy(false);
    }
  }

  async function registerForNativePush(sessionToken: string) {
    if (!Device.isDevice) return;
    const existing = await Notifications.getPermissionsAsync();
    const finalStatus =
      existing.status === 'granted'
        ? existing.status
        : (await Notifications.requestPermissionsAsync()).status;
    if (finalStatus !== 'granted') return;
    const projectId = Constants.expoConfig?.extra?.eas?.projectId;
    const tokenData = await Notifications.getExpoPushTokenAsync(projectId ? { projectId } : undefined);
    await registerNativePushToken(sessionToken, tokenData.data, Platform.OS);
  }

  async function onSubmitRequestOff() {
    if (!token) return;
    setBusy(true);
    try {
      const result = await submitRequestOff(
        token,
        requestDraft.startDate,
        requestDraft.endDate,
        requestDraft.reason,
        requestDraft.notes,
        requestDraft.isFullDay,
        requestDraft.start,
        requestDraft.end,
        requestDraft.segments
      );
      const warning = result.warnings.length ? ` Warnings: ${result.warnings.join(' ')}` : '';
      setMessage(result.ok ? `Request submitted.${warning}` : `Request not submitted.${warning}`);
      setRequestDraft({ ...requestDraft, reason: '', notes: '' });
      await loadHome(token, weekOffset);
    } catch (err) {
      setMessage(err instanceof Error ? err.message : 'Request off failed');
    } finally {
      setBusy(false);
    }
  }

  async function onUpdateRequestOff(requestId: number) {
    if (!token) return;
    setBusy(true);
    try {
      const result = await updateRequestOff(
        token,
        requestId,
        requestDraft.startDate,
        requestDraft.endDate,
        requestDraft.reason,
        requestDraft.notes,
        requestDraft.isFullDay,
        requestDraft.start,
        requestDraft.end,
        requestDraft.segments
      );
      const warning = result.warnings.length ? ` Warnings: ${result.warnings.join(' ')}` : '';
      setMessage(result.ok ? `Request updated.${warning}` : `Request not updated.${warning}`);
      await loadHome(token, weekOffset);
    } catch (err) {
      setMessage(err instanceof Error ? err.message : 'Request update failed');
    } finally {
      setBusy(false);
    }
  }

  async function onCancelRequestOff(requestId: number) {
    if (!token) return;
    setBusy(true);
    try {
      await cancelRequestOff(token, requestId);
      setMessage('Days off canceled. Schedule restored.');
      await loadHome(token, weekOffset);
    } catch (err) {
      setMessage(err instanceof Error ? err.message : 'Request cancel failed');
    } finally {
      setBusy(false);
    }
  }

  async function onWeekChange(nextWeekOffset: number) {
    setWeekOffset(nextWeekOffset);
    await loadHome(token, nextWeekOffset);
  }

  function onTabChange(tab: TabKey) {
    setActiveTab(tab);
    if (tab === 'patients') {
      void loadPatients();
    }
  }

  async function onSubmitCallCoverage(rotationId: number, coveringSurgeonId?: number) {
    if (!token) return;
    setBusy(true);
    try {
      await submitCallCoverage(token, rotationId, coveringSurgeonId);
      setMessage('On-call coverage saved.');
      await loadHome(token, weekOffset);
    } catch (err) {
      setMessage(err instanceof Error ? err.message : 'Coverage save failed');
    } finally {
      setBusy(false);
    }
  }

  async function onMarkAlertsRead() {
    if (!token) return;
    try {
      await markNativeAlertsRead(token);
      await loadHome(token, weekOffset);
    } catch (err) {
      setMessage(err instanceof Error ? err.message : 'Alert update failed');
    }
  }

  async function onCreateDayItem(date: string, title: string, notes: string, start?: string | null, end?: string | null) {
    if (!token) return;
    setBusy(true);
    try {
      await createDayItem(token, date, title, notes, start, end);
      setMessage('Personal item added.');
      await loadHome(token, weekOffset);
    } catch (err) {
      setMessage(err instanceof Error ? err.message : 'Personal item add failed');
    } finally {
      setBusy(false);
    }
  }

  async function onUpdateDayItem(itemId: number, title: string, notes: string, start?: string | null, end?: string | null) {
    if (!token) return;
    setBusy(true);
    try {
      await updateDayItem(token, itemId, title, notes, start, end);
      setMessage('Personal item updated.');
      await loadHome(token, weekOffset);
    } catch (err) {
      setMessage(err instanceof Error ? err.message : 'Personal item update failed');
    } finally {
      setBusy(false);
    }
  }

  async function onDeleteDayItem(itemId: number) {
    if (!token) return;
    setBusy(true);
    try {
      await deleteDayItem(token, itemId);
      setMessage('Personal item deleted.');
      await loadHome(token, weekOffset);
    } catch (err) {
      setMessage(err instanceof Error ? err.message : 'Personal item delete failed');
    } finally {
      setBusy(false);
    }
  }

  return (
    <View style={[styles.container, isAuthed ? styles.scheduleContainer : styles.authContainer]}>
      <StatusBar style="dark" />
      {!isAuthed ? (
        <AuthScreen
          email={email}
          code={code}
          busy={busy}
          message={message}
          onEmailChange={setEmail}
          onCodeChange={setCode}
          onRequestOtp={onRequestOtp}
          onVerifyOtp={onVerifyOtp}
        />
      ) : (
        <ScheduleScreen
          home={home}
          busy={busy}
          message={message}
          lastSync={lastSync}
          activeTab={activeTab}
          weekOffset={weekOffset}
          patientAppointments={patientAppointments}
          patientWarning={patientWarning}
          requestDraft={requestDraft}
          onTabChange={onTabChange}
          onWeekChange={onWeekChange}
          onLoadPatients={() => loadPatients()}
          onRequestDraftChange={setRequestDraft}
          onSubmitRequestOff={onSubmitRequestOff}
          onUpdateRequestOff={onUpdateRequestOff}
          onCancelRequestOff={onCancelRequestOff}
          onSubmitCallCoverage={onSubmitCallCoverage}
          onMarkAlertsRead={onMarkAlertsRead}
          onCreateDayItem={onCreateDayItem}
          onUpdateDayItem={onUpdateDayItem}
          onDeleteDayItem={onDeleteDayItem}
        />
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
  },
  authContainer: {
    backgroundColor: '#f0faf8',
    padding: 0,
  },
  scheduleContainer: {
    backgroundColor: '#edf8f6',
    padding: 16,
    paddingTop: 52,
  },
});

function defaultPatientRange(): NativeHome['range'] {
  const start = new Date();
  const end = new Date(start);
  end.setDate(start.getDate() + 6);
  return {
    start: dateToIso(start),
    end: dateToIso(end),
  };
}

function dateToIso(value: Date): string {
  const year = value.getFullYear();
  const month = String(value.getMonth() + 1).padStart(2, '0');
  const day = String(value.getDate()).padStart(2, '0');
  return `${year}-${month}-${day}`;
}
