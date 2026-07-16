# CAL Native Parity Ledger

Last updated: 2026-07-10

iOS test build target: `1.0.1 (15)` from the SwiftUI `ios/` lane.

Production decision: SwiftUI is the production iOS app. Expo/React Native is the temporary Android bridge. Jetpack Compose is the target Android app (real API auth/home/schedule/time-off/patients/coverage wired; UI polish still behind iOS). Surgeon web PWA is retired (`/surgeon/*` HTML → use-app page).

Portal parity (2026-07-10): admins can assign/clear call coverage and Block OR surgeons on portal via the same services as native. Block OR assign with schedule warnings requires an override note.

Adaptive layout (2026-07-10): `ClinicalTypography` + `CalNavigation` (NavigationStack on iOS 16+) + readable columns for iPad. Mac Catalyst and Designed for iPad are enabled in the Xcode target (`SUPPORTS_MACCATALYST`, min window 980×700). Mac is a local/dev destination only until signing and TestFlight Mac distribution are explicitly approved.

Current tracked lane imports:

- iOS SwiftUI: `ios/` with no Expo, React Native, CocoaPods, or Node build dependency.
- Android Compose target: `android/`
- Expo/React Native bridge: `legacy-react-native/` for Android only; no Expo iOS target is allowed.

| Workflow | Backend Endpoint / Contract | iOS SwiftUI | Android Expo Temporary | Android Compose Target | Production Allowed | Notes |
|---|---|---|---|---|---|---|
| Auth / OTP | `POST /api/surgeon/otp/request`, `POST /api/surgeon/otp/verify` | Production with saved-session Face ID unlock | Temporary Android bridge | Debug lane (OTP + session; no biometrics yet) | iOS + Expo Android | First login remains CAL-specific SMS/email OTP; repeat iPhone opens silently try Face ID against the saved Keychain token, then fall back to OTP with no separate visible unlock button |
| Today | `GET /api/native/home` | Production | Temporary Android bridge | Debug lane (basic) | iOS + Expo Android | At-a-glance view must match backend data |
| Daily Schedule | `GET /api/native/home` | Production | Temporary Android bridge | Debug lane (functional; UI thinner than iOS) | iOS + Expo Android | Shared date stepper + Day\|Week\|Month chrome. Day: On Call \| Off half-width pills; Clinic/OR + Personal sections; Cover from On Call |
| Week | `GET /api/native/home` | Production | Temporary Android bridge | Debug lane (functional; UI thinner than iOS) | iOS + Expo Android | Cliff-note rows (ON/OFF/Clinic·OR + meeting); tap opens Day. Shared date-range stepper |
| Month | `GET /api/native/home` | Production | Temporary Android bridge | Debug lane (letter marks; no heatmap yet) | iOS + Expo Android | Heatmap dots (call/off/clinic) + selected-day agenda below grid; Cover only from agenda; Open Day jumps to Day scope. Not a cramped 7-col text grid |
| Time Off | `/api/native/request-off*`, `GET /api/native/home` | Production | Temporary Android bridge | Debug lane (list + full-day request; no Who’s Out gantt) | iOS + Expo Android | Multi-day/half-day request form. Who’s Out is portal-style month Gantt (surgeon × days, mint approved / amber pending) with month stepper. Clinic-group warning on submit is non-blocking |
| On Call Coverage | `POST /api/native/call-coverage`, `POST /api/native/call-coverage/{id}/cancel`, portal `/admin/call-schedule/cover*` | Production (+ cancel) | Temporary Android bridge | Debug lane (submit only; cancel pending) | iOS + Expo Android | Cover sheet defaults to no surgeon selected; Save disabled until pick. Coverage shows original crossed out and covering initials. Portal can assign/clear. |
| Meetings | `GET /api/native/home` | Production | Temporary Android bridge | Debug lane | iOS + Expo Android | Today and next item display are required |
| Personal Items | `GET /api/native/home` (display today + next) | Production (display-only) | Temporary Android bridge | Debug lane (display) | iOS + Expo Android | iOS shows today + next personal items from home payload; no day-items CRUD in SwiftUI today. Legacy RN bridge has CRUD via `/surgeon/api/day-items*` but that is not the iOS spec. |
| Patient Schedule | `GET /api/native/patient-schedule` | Production | Temporary Android bridge | Debug lane | iOS + Expo Android | Must show only actual scheduled patients with correct Eastern times |
| Push Alerts | `/api/native/push-token`, `/api/native/alerts/read`, `GET /api/native/home` | Simulator/test lane implemented; needs TestFlight verification before production | Temporary Android bridge | Not integrated | iOS test only + Expo Android | iOS registers APNs tokens, decodes alert inbox/banner, and marks alerts read; production push requires APNs env and TestFlight review |
| Scheduler Block OR | `POST /api/native/scheduler/*`, portal `/admin/block-or/{id}/assign|clear` | Simulator lane + portal admin assign | Not integrated | Not integrated | iOS simulator/test + portal admin | Shared `or_block_service`. Override note required when warnings exist. Scheduler portal role remains capacity view-only. Epic release/give-back stays out of CAL. |
| Scheduler Digest | `schedule_change_events`, `server/scripts/send_scheduler_digest.py` | Not a native screen; Changes tab reads recent events | Not integrated | Not integrated | Backend test lane only | Daily 6 AM ET job target for scheduler/admin recipients. Email payload is non-PHI and summarizes last-24-hour availability changes plus open Block OR rows. |

## Ledger Rules

- Update this table in the same commit as any native workflow change.
- Mark temporary gaps plainly. Do not hide platform differences in code comments only.
- If a backend endpoint changes shape, update this ledger and the backend native contract tests together.
- Compose cannot move from `Not integrated` to production status until auth, schedule, time off, on-call coverage, patients, and push behavior all use real CAL APIs.
