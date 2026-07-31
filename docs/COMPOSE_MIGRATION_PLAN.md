# CAL Android Migration Plan: Expo → Jetpack Compose (iOS SSOT)

**Status:** Execution SSOT for Android Compose migration  
**Date:** 2026-07-31  
**Owner:** Don (sign-off at each phase exit)  
**Spec path (behavior):** `ios/CALNative/`  
**Field Android today:** `legacy-react-native/` (Expo)  
**Compose target:** `android/`  

This document is the durable execution plan. Prefer it over older Android/Compose notes in `docs/cal-native-parity-ledger.md` and `docs/SCHEDULER_AND_ANDROID_EXECUTION_PLAN.md` (both stale on OTP paths, package strategy, and Compose maturity — update those after Compose phases land, do not treat them as SSOT for this migration).

---

## 0. Decision principles

1. **iOS is SSOT.** Compose must match product behavior in `ios/CALNative/`, not Expo quirks and not invent new Android-only workflows. When Expo and iOS diverge, follow iOS.
2. **Expo is a temporary bridge.** Keep `legacy-react-native/` field-ready for Lucy until Compose is signed off side-by-side with iOS. Freeze Expo feature work except field-critical hotfixes.
3. **Shared native APIs.** Compose uses the same `/api/native/*` contracts as iOS (unified OTP, home, request-off, call-coverage, patients, alerts, push-token, scheduler). Do not invent Compose-only endpoints.
4. **FCM is the only required server delta.** `server/app/push.py` today sends Expo + APNs only. Compose needs FCM send + `provider=fcm` registration. No broader server rewrite for Compose.
5. **Portal stays Jinja.** Admin/scheduler portal remains server-rendered templates. Out of scope for this migration.
6. **No half-parity claims.** A workflow is not “done” until Don signs off Compose vs iOS as Lucy (same data, same actions, Clinical Trust chrome).

---

## 1. Current state (honest)

### Expo (field)

| Item | Value |
|------|--------|
| Path | `legacy-react-native/` |
| App | MFSA CAL |
| Version | `2.0.0` / `versionCode` **21** (`app.json`) |
| Package | `com.midfloridasurgical.calnative` |
| Status | Field-ready surgeon bridge |

**Surface (mirror of iOS surgeon shell):**

- Auth: unified `POST /api/native/otp/request` + `/verify` via `src/services/calApi.ts`
- Sections: Schedule (Day/Week/Month), Time Off, Patients
- Home: `GET /api/native/home`
- Time off CRUD: `/api/native/request-off*`
- Cover submit + cancel: `/api/native/call-coverage`, `.../cancel` (no preselected surgeon)
- Personal day-item CRUD: `/surgeon/api/day-items*` (create/update/delete + Type presets; also on iOS)
- Patients: `GET /api/native/patient-schedule`
- Push: Expo tokens → `POST /api/native/push-token` (`provider` expo); alerts mark-read
- Install path: EAS / native APK; sim via `scripts/run-expo-android-sim.sh` → AVD `CAL_Pixel_8`

### Compose (debug / partial)

| Item | Value |
|------|--------|
| Path | `android/` |
| Package / applicationId | `com.midfloridasurgical.calcompose` |
| Version | `0.1` / `versionCode` 1 |
| Shell | Title-menu Schedule \| Time Off \| Patients (`SurgeonShell.kt`) |
| Theme | `ClinicalPalette.kt` present |

**What is wired (thin vs iOS):**

- OTP + session + `GET /api/native/home` → schedule Day/Week/Month chrome
- Time off list + full-day request (`POST /api/native/request-off`)
- Cover submit (`POST /api/native/call-coverage`)
- Patients list (`GET /api/native/patient-schedule`)

**Gaps (blocking parity):**

| Gap | Detail |
|-----|--------|
| Wrong OTP path | `CalApiClient.kt` still hits `/api/surgeon/otp/*` — must use unified `/api/native/otp/*` (iOS + Expo) |
| Insecure session | `CalSessionStore.kt` uses plain `SharedPreferences` — need EncryptedSharedPreferences (or equivalent) mirroring Keychain |
| No dual-role | No unified tokens/roles / Schedule\|Scheduler switch |
| No merge / thinner schedule UI | Not pixel/behavior-matched to iOS Day/Week/Month (heatmap, cliff notes, On Call/Off pills, etc.) |
| No Who’s Out Gantt | Time Off missing portal-style month Gantt + scroll-to-today |
| Personal CRUD missing | No day-items create/update/delete + Type presets — **must port from iOS** (`DayScheduleDashboard` / `NativeScheduleStore` → `/surgeon/api/day-items*`); Expo also has it |
| Cover incomplete | Preselect / no cancel path vs iOS+Expo (no preselect + cancel) |
| No alerts / push | No bell inbox, no `alerts/read`, no FCM / `push-token` |
| No biometrics | iOS Face ID unlock not ported |
| No scheduler shell | Dual-role Block OR UI deferred unless Phase 5 is in scope |

### Server readiness

| Area | Ready? | Notes |
|------|--------|-------|
| Surgeon native APIs | Yes | `native_api.py`, `native_otp_api.py` — home, otp, request-off, call-coverage, patients, alerts, push-token, day-items (surgeon) |
| Scheduler native APIs | Yes | `native_scheduler_api.py` — home, meta, blocks CRUD/assign/clear/cases |
| Push | Partial | `push.py`: Expo + APNs only. **No FCM sender.** Compose cannot get production push until FCM is added |
| Portal | N/A | Stays Jinja; not part of Compose cutover |

### Stale docs (do not execute from these alone)

- `docs/cal-native-parity-ledger.md` — useful inventory, but mixes Expo bridge status with older Compose notes; OTP/scheduler Android rows lag this plan.
- `docs/SCHEDULER_AND_ANDROID_EXECUTION_PLAN.md` — still cites `/api/surgeon/otp/*` for Compose foundation and older package assumptions. Superseded for Android Compose execution by **this file**.

---

## 2. Target architecture

### Package ID strategy

| Phase | Expo | Compose |
|-------|------|---------|
| Side-by-side | Keep `com.midfloridasurgical.calnative` | Keep `com.midfloridasurgical.calcompose` |
| Cutover (**keep A**) | Retire / stop distributing Expo APK | **Keep** `com.midfloridasurgical.calcompose` as production applicationId |

**Rationale:** Different package IDs let Lucy install Expo and Compose on the same device for comparison. Do not rename Compose onto `calnative` mid-migration (breaks side-by-side and Play/internal identity). Cutover option A = keep `calcompose` permanently; Expo’s `calnative` ID is abandoned with the bridge.

### Module structure under `android/`

```
android/app/src/main/java/com/midfloridasurgical/calcompose/
├── MainActivity.kt
├── ui/theme/ClinicalPalette.kt          ← Clinical Trust tokens (PALETTES.md)
├── data/
│   ├── CalApiClient.kt                  ← mirror NativeCALClient.swift
│   ├── CalSessionStore.kt               ← secure storage (not plain SharedPreferences)
│   ├── SurgeonHomeStore.kt
│   └── models/                          ← Native* API models
├── auth/
│   ├── AuthScreen.kt                    ← NativeAuthView.swift
│   └── BiometricUnlock.kt               ← NativeBiometricService.swift (later phase)
├── surgeon/
│   ├── SurgeonShell.kt                  ← CALNativeTabShell.swift
│   ├── schedule/                        ← Day/Week/Month + cover sheet
│   ├── timeoff/                         ← request + Who’s Out Gantt
│   ├── patients/                        ← PatientScheduleView.swift
│   └── alerts/                          ← toolbar bell / sheet
└── scheduler/                           ← Phase 5; NativeSchedulerViews.swift
```

### Networking / auth

- Base URL: DEBUG emulator `http://10.0.2.2:3005`; release `https://cal.midfloridasurgical.com` (match current Compose/`BuildConfig` pattern; align with iOS DEBUG localhost policy).
- Headers: `Authorization: Bearer <token>`, `X-CAL-Device-Token`, `Accept: application/json`.
- OTP: **only** `POST /api/native/otp/request` and `POST /api/native/otp/verify`. Prefer `tokens.surgeon` when both roles present; support dual tokens + in-app mode switch when Phase 5 is in scope.
- Session: EncryptedSharedPreferences (or Android Keystore-backed store). Clear on sign-out.

### Navigation (mirror iOS)

- Toolbar title dropdown: **Schedule | Time Off | Patients** (+ Sign Out).
- No bottom tab bar for surgeon.
- Alerts: toolbar bell / sheet overlay (not a primary tab), matching iOS.
- Dual-role: Schedule \| Scheduler principal switch (iOS pattern) only when scheduler work is in scope.

### Design tokens

- Clinical Trust only — `ClinicalPalette.kt` / `.cursor/rules/PALETTES.md`.
- No scattered hardcoded colors; no Expo-era chrome that diverges from iOS.

---

## 3. Phased plan with exit criteria

### Phase 0 — Freeze Expo + lock SSOT checklist

**Goal:** Stop Android feature drift on Expo; lock the iOS checklist Compose will mirror.

**Deliverables**

- Expo: feature freeze except production/field hotfixes for Lucy.
- Written SSOT checklist from iOS (auth, D/W/M, cover, time off + Who’s Out, personal display rules, patients, alerts/push, optional scheduler).
- This plan accepted as execution SSOT.

**iOS to read:** `CALNativeTabShell.swift`, `NativeAuthView.swift`, `NativeSessionService.swift`, schedule/time-off/cover/patient/push files under `ios/CALNative/`.

**Compose:** docs only (no feature code required beyond triage).

**API:** none new.

**Test plan:** N/A product; confirm Expo `2.0.0/21` still installs for Lucy.

**Exit criteria:** Don confirms freeze + checklist. Expo remains the only field Android until later phases pass.

---

### Phase 1 — Auth + session + home fetch parity

**Goal:** Login and home payload match iOS/Expo contracts.

**Deliverables**

- Switch `CalApiClient` OTP to `/api/native/otp/request` + `/verify`.
- Parse unified verify payload (`token` / `tokens` / `roles`); persist securely.
- `GET /api/native/home` loads for authenticated session; unauthorized clears session.
- Auth UI parity with `NativeAuthView.swift` (email/phone copy, OTP entry, errors).

**iOS mirror:** `NativeAuthView.swift`, `NativeSessionService.swift`, `NativeAuthAPIModels.swift`, `NativeCALClient.swift` (unified OTP + `fetchHome`), `CALKeychain.swift`.

**Compose touch:** `auth/AuthScreen.kt`, `data/CalApiClient.kt`, `data/CalSessionStore.kt`, `data/models/AuthModels.kt`, `data/SurgeonHomeStore.kt`, `MainActivity.kt`.

**API contracts**

- `POST /api/native/otp/request` `{ email }`
- `POST /api/native/otp/verify` `{ email, code }` → tokens/roles
- `GET /api/native/home?start=&end=`

**Test plan**

- Emulator DEBUG: local OTP `654321` (mac-dev / plant rules) against local API.
- Prod-pointing debug only with Don approval: Lucy/Chris/Don accounts.
- Session survives process death; sign-out clears storage.

**Exit criteria:** Don signs off Compose login + home data side-by-side with iOS (same surgeon, same date range).

---

### Phase 2 — Schedule Day/Week/Month + personal + cover

**Goal:** Surgeon schedule chrome and cover match iOS behavior.

**Deliverables**

- Day: On Call \| Off pills, Clinic/OR + Personal sections, meetings; Cover from On Call.
- Week: cliff-note rows; tap → Day scope (not a dead modal).
- Month: heatmap-style marks + selected-day agenda; Cover from agenda; Open Day → Day scope.
- Personal: **full CRUD from iOS SSOT** — create/update/delete personal day-items with Type presets (`PersonalItemPresets`), not display-only. Port from iOS (`DayScheduleDashboard` / `NativeScheduleStore`); Expo also has CRUD — do not invent Android-only UX.
- Cover sheet: **no preselected surgeon**; Save disabled until pick; **cancel coverage** via `POST /api/native/call-coverage/{id}/cancel`.
- Shared date stepper matching iOS.

**iOS mirror:** `DayScheduleDashboard.swift` (Personal editor + Type presets), `NativeScheduleStore.swift` (`createPersonalItem` / `updatePersonalItem` / `deletePersonalItem`), `ScheduleWeekViews.swift`, `ScheduleMonthViews.swift`, `CallCoverageViews.swift`, `NativeCallCoverageAPIModels.swift`, schedule pieces in `CALNativeRootView.swift` / `NativeScheduleProjection.swift`.

**Compose touch:** `surgeon/schedule/ScheduleHomeScreen.kt`, `CallCoverageSheet.kt`, new day/week/month pieces as needed, Personal editor + day-item API client, models in `ScheduleUiModels.kt` / `HomeModels.kt`.

**API contracts**

- `GET /api/native/home`
- `POST|PUT|DELETE /surgeon/api/day-items*` (Personal CRUD; same as iOS `NativeCALClient`)
- `POST /api/native/call-coverage`
- `POST /api/native/call-coverage/{coverage_id}/cancel`

**Test plan**

- Side-by-side screenshots: same Lucy day with call, off, clinic, personal, meeting.
- Personal: add (preset + Other), edit, delete; confirm home/day refresh matches iOS.
- Cover assign + cancel round-trip; verify crossed-out original / covering initials like iOS.
- Week/month navigation into Day preserves date.

**Exit criteria:** Don signs off Schedule + Cover vs iOS as Lucy. No “thinner but good enough” hand-wave.

---

### Phase 3 — Time Off + Who’s Out Gantt

**Goal:** Request-off parity + portal-style Who’s Out month Gantt with scroll-to-today.

**Deliverables**

- Multi-day / half-day request form parity with iOS (`TimeOffRequestSheet` / segments).
- List pending/approved; edit/cancel only if iOS supports it (mirror exactly).
- Who’s Out: surgeon × days Gantt (mint approved / amber pending), month stepper, **scroll-to-today**.
- Clinic-group warning on submit non-blocking (match iOS).

**iOS mirror:** `TimeOffViews.swift`, `TimeOffRequestSheet.swift`, `TimeOffMonthViews.swift`, `NativeTimeOffAPIModels.swift`.

**Compose touch:** `surgeon/timeoff/TimeOffScreen.kt` (+ Gantt composables).

**API contracts**

- `POST /api/native/request-off`
- `PUT /api/native/request-off/{id}` / `DELETE ...` if used by iOS
- Who’s Out data from home payload / same fields iOS uses (no new endpoint unless iOS already has one)

**Test plan**

- Submit full-day and half-day; confirm on iOS and portal.
- Gantt shows peers; scroll lands on today; month stepper stable.

**Exit criteria:** Don signs off Time Off + Who’s Out vs iOS.

---

### Phase 4 — Alerts + Patients + push (FCM + server)

**Goal:** Patients parity; alert inbox; Compose devices receive push via FCM.

**Deliverables**

- Patients: `GET /api/native/patient-schedule` — Eastern times, real scheduled patients only; UI match `PatientScheduleView.swift`.
- Alerts: decode home alert inbox; toolbar bell + sheet; `POST /api/native/alerts/read`.
- FCM client: obtain token, `POST /api/native/push-token` with `platform=android`, `provider=fcm`.
- **Server:** extend `server/app/push.py` `send_native_push_to_surgeon` to send FCM for `provider=fcm` tokens (keep Expo + APNs). Register path already on `/api/native/push-token` — confirm provider field accepted.
- Tap notification refreshes home / deep-links sensibly (match iOS intent, Android idioms OK).

**iOS mirror:** `PatientScheduleView.swift`, alert UI in tab shell / schedule, `NativePushRegistrar.swift`, `registerPushToken` in `NativeCALClient.swift`.

**Compose touch:** `patients/PatientScheduleScreen.kt`, new alerts UI, FCM service/module, `CalApiClient` push + alerts methods.

**API / server**

- `GET /api/native/patient-schedule`
- `POST /api/native/alerts/read`
- `POST /api/native/push-token`
- `push.py`: **FCM send path** (only required server delta)

**Test plan**

- Patients match iOS for same window.
- Mark alerts read; unread badge clears.
- Plant push to FCM token; device receives; Expo/APNs regression smoke still green.

**Exit criteria:** Don signs off Patients + Alerts + at least one real FCM delivery on a Compose build.

---

### Phase 5 — Dual-role scheduler (explicit call) **or defer**

**Goal:** Either ship iOS-parity scheduler on Compose, or explicitly defer with Don’s call recorded here.

**If in scope — deliverables**

- Unified OTP already returns scheduler token; in-app Schedule \| Scheduler switch.
- Scheduler shell: open blocks, assign/clear, meta, create/edit/cancel capacity as iOS (`NativeSchedulerViews.swift`).
- APIs under `/api/native/scheduler/*` only.

**iOS mirror:** `NativeSchedulerViews.swift`, `NativeSchedulerModels.swift`, scheduler methods in `NativeCALClient.swift`.

**Compose touch:** new `scheduler/` package + shell routing from auth/session.

**API contracts:** `GET /home`, `GET /meta`, `POST/PATCH/DELETE /blocks*`, assign/update/remove/clear, cases — as iOS uses.

**Test plan:** Scheduler test account: create/assign/clear on Compose; verify portal + iOS see same Block OR state.

**Exit criteria (ship):** Don signs off scheduler vs iOS.  
**Exit criteria (defer):** Don records “Phase 5 deferred”; Compose surgeon-only may proceed to Phase 6; ledger must say scheduler Not integrated on Compose.

---

### Phase 6 — Hardening, distribute, cutover, retire Expo

**Goal:** Field Compose; Expo retired.

**Deliverables**

- Biometrics unlock on relaunch (BiometricPrompt ↔ `NativeBiometricService.swift`) if iOS requires it for parity sign-off.
- Release/internal signing; versionName/versionCode policy; Play internal or sideload path for Lucy.
- Guardrails: `./scripts/check-native-guardrails.sh` (+ `--release` when applicable).
- Update parity ledger: Compose rows → Production for signed-off workflows.
- Cutover: stop distributing Expo APK; keep Expo repo frozen for emergency rollback APK only.
- Package: **keep A** — production remains `com.midfloridasurgical.calcompose`.

**Test plan**

- Lucy installs Compose release/internal build; day-of-work smoke (login, schedule, cover, time off, patients, push).
- Rollback drill: reinstall Expo `calnative` APK still works.

**Exit criteria:** Don signs off field cutover. Expo no longer the production Android bridge.

---

## 4. Cutover plan for Lucy / field

1. **Side-by-side period (Phases 1–5):** Lucy keeps Expo `com.midfloridasurgical.calnative` as daily driver. Install Compose `com.midfloridasurgical.calcompose` alongside for comparison (same device OK).
2. **How she installs Compose:** Internal/signed APK (or Play internal testing) built from `android/` — not Expo Go, not EAS Expo bridge. Document adb/`am start` package for Compose separately from `scripts/run-expo-android-sim.sh`.
3. **Sign-off:** Don + Lucy walk iOS vs Compose checklist for a real week.
4. **Cutover:** Compose becomes daily driver; Expo distribution stops.
5. **Rollback:** Keep last known-good Expo APK (`2.0.0/21` or later hotfix). Reinstall `calnative` — no data migration required between packages.
6. **Server:** FCM must be live before cutover if push is in the sign-off checklist (Phase 4).

---

## 5. Risks & non-goals

### Risks

| Risk | Mitigation |
|------|------------|
| Compose OTP still on legacy `/api/surgeon/otp/*` | Phase 1 first; block further UI until fixed |
| Inventing Android-only Personal UX | Port Personal CRUD + Type presets from iOS SSOT (`DayScheduleDashboard` / `NativeScheduleStore` / `/surgeon/api/day-items*`); Expo parity is secondary |
| Push gap | FCM in `push.py` is mandatory for Phase 4; Expo push path stays for bridge |
| Dual package confusion | Clear install docs; different app labels/icons if needed |
| Premature Expo retirement | Phase 6 only after Don field sign-off |
| Stale execution docs | This file is SSOT; refresh ledger/old plan after phases |

### Non-goals

- Do **not** rewrite server for Compose except FCM (+ any trivial `push-token` provider acceptance).
- Portal stays Jinja — no React admin, no Compose web.
- No half-parity claims; no “UI thinner but shipping” for field cutover.
- No Expo iOS target; no new feature work on Expo except hotfixes.
- Do not force applicationId rename to `calnative` at cutover (strategy A).

---

## 6. Immediate next 2 weeks (concrete task list)

Week-oriented execution list; order matters.

1. **Accept this plan as SSOT**; mark Phase 0 freeze on Expo features (hotfixes only).
2. **Phase 1 OTP fix:** point Compose at `/api/native/otp/*`; parse unified tokens/roles.
3. **Secure session store:** replace plain `SharedPreferences` with EncryptedSharedPreferences.
4. **Home smoke:** Lucy (or Don-as-Lucy) login + `GET /api/native/home` side-by-side with iOS.
5. **Cover parity spike:** remove preselect; wire cancel endpoint; screenshot vs iOS.
6. **Schedule Day chrome:** On Call/Off pills + sections alignment (start Phase 2).
7. **Who’s Out Gantt spike:** read iOS `TimeOffMonthViews.swift`; sketch Compose Gantt + scroll-to-today (Phase 3 prep).
8. **FCM design note:** Firebase project + `push.py` FCM send sketch (no need to finish push until Phase 4, but unblock credentials).
9. **Do not** start scheduler UI until Phase 1–2 exit or Don explicitly pulls Phase 5 forward.
10. **Do not** deprecate Expo or change Lucy’s daily APK.

---

## Appendix A — iOS → Compose file map

| iOS (`ios/CALNative/`) | Compose (`android/.../calcompose/`) |
|------------------------|-------------------------------------|
| `NativeAuthView.swift` | `auth/AuthScreen.kt` |
| `NativeSessionService.swift` / `CALKeychain.swift` | `data/CalSessionStore.kt` (+ biometrics later) |
| `NativeCALClient.swift` | `data/CalApiClient.kt` |
| `NativeAPIModels.swift` / `NativeAuthAPIModels.swift` / home models | `data/models/*` |
| `CALNativeTabShell.swift` | `surgeon/SurgeonShell.kt` |
| `DayScheduleDashboard.swift` (+ Personal editor / Type presets) | `surgeon/schedule/` day UI + Personal CRUD |
| `NativeScheduleStore.swift` (`*PersonalItem` / day-items) | Personal day-item API client |
| `ScheduleWeekViews.swift` | `surgeon/schedule/` week UI |
| `ScheduleMonthViews.swift` | `surgeon/schedule/` month UI |
| `CallCoverageViews.swift` | `surgeon/schedule/CallCoverageSheet.kt` |
| `TimeOffViews.swift` / `TimeOffRequestSheet.swift` / `TimeOffMonthViews.swift` | `surgeon/timeoff/*` |
| `PatientScheduleView.swift` | `surgeon/patients/PatientScheduleScreen.kt` |
| Alert UI in tab shell | `surgeon/alerts/` (to add) |
| `NativePushRegistrar.swift` | FCM registrar + `push-token` API |
| `NativeBiometricService.swift` | `auth/BiometricUnlock.kt` (Phase 6) |
| `NativeSchedulerViews.swift` | `scheduler/*` (Phase 5) |
| `CALNativeComponents.swift` / Clinical Trust | `ui/theme/ClinicalPalette.kt` |

---

## Appendix B — API quick reference (Compose must use)

```
POST /api/native/otp/request
POST /api/native/otp/verify
GET  /api/native/home
GET  /api/native/patient-schedule
POST /api/native/request-off
PUT  /api/native/request-off/{id}
DELETE /api/native/request-off/{id}
POST /surgeon/api/day-items         # Personal create (Phase 2; iOS SSOT)
PUT  /surgeon/api/day-items/{id}    # Personal update
DELETE /surgeon/api/day-items/{id}  # Personal delete
POST /api/native/call-coverage
POST /api/native/call-coverage/{id}/cancel
POST /api/native/alerts/read
POST /api/native/push-token          # provider=fcm for Compose
GET  /api/native/scheduler/home      # Phase 5
GET  /api/native/scheduler/meta
POST|PATCH|DELETE /api/native/scheduler/blocks...
```

Personal day-items — **required Phase 2**: iOS already has create/update/delete + Type presets (`DayScheduleDashboard` / `NativeScheduleStore`); Compose must port that SSOT (Expo also has CRUD).

---

## Appendix C — FCM note (required server delta)

- Today: `send_native_push_to_surgeon` in `server/app/push.py` splits `provider == "expo"` vs APNs. No FCM branch.
- Compose: register FCM device tokens with `provider=fcm` via `POST /api/native/push-token`.
- Server work: implement `_send_fcm_push` (or equivalent) and include fcm tokens in `send_native_push_to_surgeon`. Keep Expo path until bridge retired; keep APNs for iOS.
- Do not replace portal web-push.

---

*End of execution SSOT. Update phase checkboxes / exit notes in session memory when a phase clears; refresh parity ledger after Compose production rows change.*
