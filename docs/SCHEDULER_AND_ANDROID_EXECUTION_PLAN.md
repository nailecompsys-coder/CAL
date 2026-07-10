# Scheduler + Android Parity — Execution Plan

Last updated: 2026-07-09  
**Goal:** Scheduler running on mobile + portal; Jetpack Compose mirroring iOS SwiftUI exactly.

---

## Current State Summary

### Scheduler

| Component | Status | Gap |
|-----------|--------|-----|
| Server API + models | ✅ Built | Digest cron not on prod |
| Admin Block OR create + grid | ✅ Built | `scheduler-availability` not in nav |
| iOS scheduler shell | ✅ Simulator lane | Needs TestFlight verification |
| Android scheduler | ❌ Not started | Full port required |
| Portal assign surgeon | ❌ By design | Mobile-only placement |

### Android vs iOS

| Area | iOS | Android Compose |
|------|-----|-----------------|
| Auth + API | ✅ Real | ❌ None |
| 3-section nav | ✅ Title menu | ❌ Wrong 5-tab mock |
| Schedule D/W/M | ✅ | ❌ Placeholder |
| Time Off | ✅ | ❌ Placeholder |
| Patients | ✅ | ❌ Mock in Today tab |
| Alerts + Push | ✅ APNs | ❌ None |
| Scheduler role | ✅ | ❌ None |
| Face ID unlock | ✅ | ❌ None |

**iOS spec path:** `ios/CALNative/`  
**Android target:** `android/` — greenfield port, not incremental mock edits

---

## Phase A — Harden Guardrails (Do First)

**Owner:** Docs + scripts  
**Duration:** 1 session

| Task | File | Done when |
|------|------|-----------|
| Agent guardrails doc | `docs/CAL_AGENT_GUARDRAILS.md` | Committed |
| This execution plan | `docs/SCHEDULER_AND_ANDROID_EXECUTION_PLAN.md` | Committed |
| Update agent context | `docs/ai/CURSOR_CONTEXT.md` | Points to guardrails + plan |
| Android mock detection in guardrails | `scripts/check-native-guardrails.sh` | Fails on hardcoded mock names in `android/` |
| Fix parity ledger personal items note | `docs/cal-native-parity-ledger.md` | Matches iOS code (display-only) |

**Gate:** `./scripts/check-native-guardrails.sh`

---

## Phase B — Scheduler Portal Complete

**Owner:** `server/`  
**Duration:** 1–2 sessions

| # | Task | Files | Acceptance |
|---|------|-------|------------|
| B1 | Add nav link for Scheduler Availability | `server/app/templates/base_admin.html` | ✅ Admins + schedulers can reach `/admin/scheduler-availability` |
| B2 | Scheduler role: confirm read-only Block OR works | `server/app/auth.py`, `block_or.html` | ✅ Scheduler sees grid, cannot create/edit/delete |
| B3 | Wire digest cron on prod `.62` | `server/scripts/send_scheduler_digest.py` + `scripts/install-scheduler-digest-cron.sh` | ✅ Script + dry-run + install helper ready; **prod cron install waits for Don** |
| B4 | Admin smoke test doc | `docs/RELEASE_CHECKLIST.md` | ✅ Block OR → mobile assign → digest section added |
| B5 | Contract tests if portal routes change | `server/tests/` | ✅ digest + scheduler portal auth tests |

**Gate:** Manual admin flow: create block → verify on iOS scheduler shell → assign surgeon → verify on clinic schedule.

**Do not build:** Portal surgeon assignment UI (mobile-first by product decision).

---

## Phase C — Scheduler iOS Production

**Owner:** `ios/`  
**Duration:** 1 session + TestFlight

| # | Task | Files | Acceptance |
|---|------|-------|------------|
| C1 | TestFlight build from `ios/` only | Xcode archive | Build 1.0.1 (14)+ |
| C2 | Scheduler OTP on real device | `NativeSessionService.swift` | Email OTP → scheduler shell |
| C3 | Assign/clear block on prod API | `NativeSchedulerViews.swift` | Writes non-PHI slot |
| C4 | Changes tab matches digest events | `NativeSchedulerViews.swift` | Recent events visible |
| C5 | Update parity ledger | `docs/cal-native-parity-ledger.md` | Status → Production |

**Gate:** `./scripts/check-native-guardrails.sh --release` + TestFlight install on scheduler test account.

---

## Phase D — Android Foundation (Mirror iOS Shell)

**Owner:** `android/`  
**Duration:** 2–3 sessions  
**Spec:** `ios/CALNative/CALNativeRootView.swift`, `CALNativeTabShell.swift`

### D1 — Project structure

Replace monolithic `MainActivity.kt` with:

```
android/app/src/main/java/com/midfloridasurgical/calcompose/
├── MainActivity.kt
├── ui/theme/ClinicalPalette.kt          ← from CALNativeComponents.swift
├── data/
│   ├── CalApiClient.kt                  ← mirror NativeCALClient.swift
│   ├── CalSessionStore.kt               ← mirror NativeScheduleStore.swift
│   └── models/                          ← mirror NativeAPIModels.swift etc.
├── auth/
│   ├── AuthScreen.kt                    ← NativeAuthView.swift
│   └── BiometricUnlock.kt               ← NativeBiometricService.swift
└── surgeon/
    ├── SurgeonShell.kt                  ← CALNativeTabShell.swift (3-section menu)
    ├── schedule/                        ← ScheduleHomeView, Day/Week/Month
    ├── timeoff/                         ← TimeOffHomeView
    └── patients/                        ← PatientScheduleView.swift
```

### D2 — Delete wrong Android UI

Remove from `MainActivity.kt`:

- `TodayDashboard` mock
- `MessagesPreview` tab
- `ProfilePreview` tab
- 5-tab `NavigationBar`
- All hardcoded "Chris Johnson" data

### D3 — API layer (surgeon)

Port endpoints from `NativeCALClient.swift`:

| Endpoint | Priority |
|----------|----------|
| `POST /api/surgeon/otp/request` | P0 |
| `POST /api/surgeon/otp/verify` | P0 |
| `GET /api/native/home` | P0 |
| `POST /api/native/request-off` | P1 |
| `POST /api/native/call-coverage` | P1 |
| `GET /api/native/patient-schedule` | P1 |
| `POST /api/native/alerts/read` | P1 |
| `POST /api/native/push-token` | P2 |

Headers: `Authorization: Bearer`, `X-CAL-Device-Token`.

### D4 — Navigation (match iOS exactly)

- **3 sections** switched from toolbar title dropdown: Schedule | Time Off | Patients
- Sign out in same menu
- Alerts as top banner overlay (not a tab)
- No bottom tab bar for surgeon app

**Gate:** `./gradlew :app:assembleDebug` + OTP login + home loads real data.

---

## Phase E — Android Surgeon Workflows (iOS Parity)

**Owner:** `android/`  
**Duration:** 3–4 sessions  
**Spec:** One iOS file per Android screen (see mapping below)

| iOS file | Android target | Workflow |
|----------|----------------|----------|
| `ScheduleHomeView` in `CALNativeRootView.swift` | `surgeon/schedule/ScheduleHomeScreen.kt` | Day/Week/Month segmented |
| `DayScheduleDashboard.swift` | `ScheduleDayScreen.kt` | On-call, off, schedule, meetings, personal |
| `ScheduleWeekViews.swift` | `ScheduleWeekScreen.kt` | Compact week cards |
| `ScheduleMonthViews.swift` | `ScheduleMonthScreen.kt` | Month grid |
| `CallCoverageViews.swift` | `CallCoverageSheet.kt` | Coverage picker |
| `TimeOffViews.swift` + `TimeOffRequestSheet.swift` | `timeoff/*.kt` | Month pills + request form |
| `PatientScheduleView.swift` | `patients/PatientScheduleScreen.kt` | 7-day Aprima |
| `CALNativeTabShell.swift` | `SurgeonShell.kt` | Alert banner + inbox |

**Behaviors to match iOS (not legacy RN):**

- Week/month tap → switch to Day scope (not modal sheet)
- Personal items: display-only from home (no day-items CRUD unless iOS adds it first)
- Time off: submit only (no edit/cancel unless iOS adds it first)

**Gate:** Side-by-side screenshot comparison iOS simulator vs Android emulator for each section.

---

## Phase F — Android Scheduler Role

**Owner:** `android/`  
**Duration:** 1–2 sessions  
**Spec:** `ios/CALNative/NativeSchedulerViews.swift`

| iOS | Android |
|-----|---------|
| `NativeSchedulerShell` | `scheduler/SchedulerShell.kt` |
| Open Blocks tab | `SchedulerOpenBlocksScreen.kt` |
| Changes tab | `SchedulerChangesScreen.kt` |
| `SchedulerAssignSheet` | `SchedulerAssignSheet.kt` |

API endpoints (from `NativeCALClient.swift`):

```
POST /api/native/scheduler/otp/request
POST /api/native/scheduler/otp/verify
GET  /api/native/scheduler/home
GET  /api/native/scheduler/blocks/{id}
POST /api/native/scheduler/blocks/{id}/assign
POST /api/native/scheduler/blocks/{id}/clear
```

Auth routing: try scheduler OTP first (mirror `NativeSessionService.swift`).

**Gate:** Scheduler test account can assign block on Android against prod/staging API.

---

## Phase G — Android Push + Biometrics + Release

| # | Task | Acceptance |
|---|------|------------|
| G1 | FCM push token → `POST /api/native/push-token` | Token registered |
| G2 | Notification → refresh home | Data updates |
| G3 | BiometricPrompt on relaunch | Saved session unlock |
| G4 | Update parity ledger — all rows `Production` for Compose | Ledger complete |
| G5 | Deprecate `legacy-react-native/` bridge | Don approval |

**Gate:** `./scripts/check-native-guardrails.sh --release` + parity ledger shows Compose production for all surgeon + scheduler workflows.

---

## Workstream Priority

```
Phase A (guardrails) ──► Phase B (portal) + Phase C (iOS scheduler prod)
                              │
                              ▼
                    Phase D (Android foundation)
                              │
                              ▼
                    Phase E (surgeon parity)
                              │
                              ▼
                    Phase F (scheduler parity)
                              │
                              ▼
                    Phase G (push + release)
```

**Parallel OK:** B + C while D starts. E blocks on D. F blocks on D + C verification.

---

## Definition of Done

### Scheduler

- [ ] Admin creates open Block OR in portal
- [ ] Scheduler assigns surgeon on iOS (TestFlight verified)
- [ ] Scheduler assigns surgeon on Android Compose
- [ ] Surgeon sees assignment on native home
- [ ] Digest email runs daily on prod (or Changes tab accepted as substitute until cron live)
- [ ] Parity ledger updated

### Android = iOS

- [ ] Same 3-section navigation (no extra tabs)
- [ ] All surgeon workflows use real APIs
- [ ] Scheduler shell matches iOS
- [ ] No mock/hardcoded data in `android/`
- [ ] `./scripts/check-native-guardrails.sh --release` passes
- [ ] Don sign-off on side-by-side parity review

---

## iOS → Android File Map (Copy Spec)

| iOS (`ios/CALNative/`) | Purpose |
|------------------------|---------|
| `CALNativeRootView.swift` | Root routing, bootstrap |
| `CALNativeTabShell.swift` | 3-section shell + alerts |
| `CALNativeComponents.swift` | Design tokens |
| `NativeCALClient.swift` | API client |
| `NativeScheduleStore.swift` | State |
| `NativeSessionService.swift` | Auth + scheduler routing |
| `NativeAuthView.swift` | OTP UI |
| `NativeSchedulerViews.swift` | Scheduler shell |
| `DayScheduleDashboard.swift` | Day view |
| `ScheduleWeekViews.swift` | Week view |
| `ScheduleMonthViews.swift` | Month view |
| `CallCoverageViews.swift` | Coverage sheet |
| `TimeOffViews.swift` | Time off home |
| `TimeOffRequestSheet.swift` | Request form |
| `PatientScheduleView.swift` | Patients |
| `NativePushRegistrar.swift` | Push |
| `NativeBiometricService.swift` | Biometrics |
| `CALKeychain.swift` | Secure storage |

**Do not use** `legacy-react-native/src/features/schedule/ScheduleScreen.tsx` as the UI spec — use iOS SwiftUI only.
