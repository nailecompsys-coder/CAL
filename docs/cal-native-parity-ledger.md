# CAL Native Parity Ledger

Last updated: 2026-07-09

iOS test build target: `1.0.1 (13)` from the SwiftUI `ios/` lane.

Production decision: SwiftUI is the production iOS app. Expo/React Native is the temporary Android bridge. Jetpack Compose is the target Android app but is not production until it has real CAL API integration and parity approval.

Current tracked lane imports:

- iOS SwiftUI: `ios/` with no Expo, React Native, CocoaPods, or Node build dependency.
- Android Compose target: `android/`
- Expo/React Native bridge: `legacy-react-native/` for Android only; no Expo iOS target is allowed.

| Workflow | Backend Endpoint / Contract | iOS SwiftUI | Android Expo Temporary | Android Compose Target | Production Allowed | Notes |
|---|---|---|---|---|---|---|
| Auth / OTP | `POST /api/surgeon/otp/request`, `POST /api/surgeon/otp/verify` | Production with saved-session Face ID unlock | Temporary Android bridge | Not integrated | iOS + Expo Android | First login remains CAL-specific SMS/email OTP; repeat iPhone opens silently try Face ID against the saved Keychain token, then fall back to OTP with no separate visible unlock button |
| Today | `GET /api/native/home` | Production | Temporary Android bridge | Not integrated | iOS + Expo Android | At-a-glance view must match backend data |
| Daily Schedule | `GET /api/native/home` | Production | Temporary Android bridge | Not integrated | iOS + Expo Android | Shared date stepper + Day\|Week\|Month chrome. Day: On Call \| Off half-width pills; Clinic/OR + Personal sections; Cover from On Call |
| Week | `GET /api/native/home` | Production | Temporary Android bridge | Not integrated | iOS + Expo Android | Cliff-note rows (ON/OFF/Clinic·OR + meeting); tap opens Day. Shared date-range stepper |
| Month | `GET /api/native/home` | Production | Temporary Android bridge | Not integrated | iOS + Expo Android | Heatmap dots (call/off/clinic) + selected-day agenda below grid; Cover only from agenda; Open Day jumps to Day scope. Not a cramped 7-col text grid |
| Time Off | `/api/native/request-off*`, `GET /api/native/home` | Production | Temporary Android bridge | Not integrated | iOS + Expo Android | Multi-day/half-day request form. Who’s Out is portal-style month Gantt (surgeon × days, mint approved / amber pending) with month stepper. Clinic-group warning on submit is non-blocking |
| On Call Coverage | `POST /api/native/call-coverage`, `GET /api/native/home` | Production | Temporary Android bridge | Not integrated | iOS + Expo Android | Cover sheet defaults to no surgeon selected; Save disabled until pick. Coverage shows original crossed out and covering initials |
| Meetings | `GET /api/native/home` | Production | Temporary Android bridge | Not integrated | iOS + Expo Android | Today and next item display are required |
| Personal Items | `GET /api/native/home` (display today + next) | Production (display-only) | Temporary Android bridge | Not integrated | iOS + Expo Android | iOS shows today + next personal items from home payload; no day-items CRUD in SwiftUI today. Legacy RN bridge has CRUD via `/surgeon/api/day-items*` but that is not the iOS spec. |
| Patient Schedule | `GET /api/native/patient-schedule` | Production | Temporary Android bridge | Not integrated | iOS + Expo Android | Must show only actual scheduled patients with correct Eastern times |
| Push Alerts | `/api/native/push-token`, `/api/native/alerts/read`, `GET /api/native/home` | Simulator/test lane implemented; needs TestFlight verification before production | Temporary Android bridge | Not integrated | iOS test only + Expo Android | iOS registers APNs tokens, decodes alert inbox/banner, and marks alerts read; production push requires APNs env and TestFlight review |
| Scheduler Block OR | `POST /api/native/scheduler/otp/request`, `POST /api/native/scheduler/otp/verify`, `GET /api/native/scheduler/home`, `GET /api/native/scheduler/blocks/{id}`, `POST /api/native/scheduler/blocks/{id}/assign` | Simulator lane implemented | Not integrated | Not integrated | iOS simulator/test only | Mobile-first scheduler lane. Schedulers can view open Block OR time, review availability warnings, assign a surgeon with start time and case count, and write a non-PHI CAL schedule slot. Release/give-back/cancel and AH report state are not active CAL workflows because Epic controls those. |
| Scheduler Digest | `schedule_change_events`, `server/scripts/send_scheduler_digest.py` | Not a native screen; Changes tab reads recent events | Not integrated | Not integrated | Backend test lane only | Daily 6 AM ET job target for scheduler/admin recipients. Email payload is non-PHI and summarizes last-24-hour availability changes plus open Block OR rows. |

## Ledger Rules

- Update this table in the same commit as any native workflow change.
- Mark temporary gaps plainly. Do not hide platform differences in code comments only.
- If a backend endpoint changes shape, update this ledger and the backend native contract tests together.
- Compose cannot move from `Not integrated` to production status until auth, schedule, time off, on-call coverage, patients, and push behavior all use real CAL APIs.
