# CAL Native Parity Ledger

Last updated: 2026-07-01

Production decision: SwiftUI is the production iOS app. Expo/React Native is the temporary Android bridge. Jetpack Compose is the target Android app but is not production until it has real CAL API integration and parity approval.

Current tracked lane imports:

- iOS SwiftUI: `ios/` with no Expo, React Native, CocoaPods, or Node build dependency.
- Android Compose target: `android/`
- Expo/React Native bridge: `legacy-react-native/`

| Workflow | Backend Endpoint / Contract | iOS SwiftUI | Android Expo Temporary | Android Compose Target | Production Allowed | Notes |
|---|---|---|---|---|---|---|
| Auth / OTP | `POST /api/surgeon/otp/request`, `POST /api/surgeon/otp/verify` | Production | Temporary Android bridge | Not integrated | iOS + Expo Android | SMS/email OTP text must remain CAL-specific |
| Today | `GET /api/native/home` | Production | Temporary Android bridge | Not integrated | iOS + Expo Android | At-a-glance view must match backend data |
| Daily Schedule | `GET /api/native/home` | Production | Temporary Android bridge | Not integrated | iOS + Expo Android | Daily view is required for all device users |
| Week | `GET /api/native/home` | Production | Temporary Android bridge | Not integrated | iOS + Expo Android | Week navigation must use shared date range semantics |
| Month | `GET /api/native/home` | Production | Temporary Android bridge | Not integrated | iOS + Expo Android | Month must show meaningful labels, not anonymous dots |
| Time Off | `/api/native/request-off*`, `GET /api/native/home` | Production | Temporary Android bridge | Not integrated | iOS + Expo Android | Supports multi-day and half-day segment selection |
| On Call Coverage | `POST /api/native/call-coverage`, `GET /api/native/home` | Production | Temporary Android bridge | Not integrated | iOS + Expo Android | Coverage shows original crossed out and covering initials |
| Meetings | `GET /api/native/home` | Production | Temporary Android bridge | Not integrated | iOS + Expo Android | Today and next item display are required |
| Personal Items | `/surgeon/api/day-items*`, `GET /api/native/home` | Production | Temporary Android bridge | Not integrated | iOS + Expo Android | Today and next item display are required |
| Patient Schedule | `GET /api/native/patient-schedule` | Production | Temporary Android bridge | Not integrated | iOS + Expo Android | Must show only actual scheduled patients with correct Eastern times |
| Push Alerts | `/api/native/push-token`, `/api/native/alerts/read`, `GET /api/native/home` | Needs explicit iOS release verification | Temporary Android bridge | Not integrated | Expo Android only until iOS verified | Native push parity must be verified before marking iOS production-complete |

## Ledger Rules

- Update this table in the same commit as any native workflow change.
- Mark temporary gaps plainly. Do not hide platform differences in code comments only.
- If a backend endpoint changes shape, update this ledger and the backend native contract tests together.
- Compose cannot move from `Not integrated` to production status until auth, schedule, time off, on-call coverage, patients, and push behavior all use real CAL APIs.
