# CAL Native Stack Guardrails

Last updated: 2026-07-01

## Decision

SwiftUI is the production iOS app. Jetpack Compose is the target Android app. Expo/React Native is the temporary Android bridge only until Compose reaches parity. React Native iOS is not a production lane.

## Production Lanes

| Lane | Source | Status | Release Rule |
|---|---|---|---|
| Backend/API | `../cal-app` | Production source of truth | API changes must preserve web and native contracts |
| iOS | `ios/CALNative` | Production/TestFlight lane | Only SwiftUI builds may ship to TestFlight |
| Android temporary | this Expo/React Native app | Android bridge | Android-only bridge until Compose is ready |
| Android target | `../../android-compose-prototype` | Prototype | Not production until real API integration and parity approval |

## Non-Negotiable Rules

- No native client may invent workflow behavior that is not backed by a documented backend endpoint and backend contract test.
- Any native source change must update `docs/cal-native-parity-ledger.md` in the same commit unless it is a pure comment or formatting-only change.
- React Native iOS builds are experimental only and must not be sent to TestFlight.
- Android must match the SwiftUI screen and workflow unless the parity ledger marks a temporary approved gap.
- Build artifacts, dependency folders, local Expo state, Xcode archives, IPAs, APKs, and DerivedData must not be staged or tracked.

## Required Preflight Commands

Before TestFlight or Android handoff:

```sh
./scripts/check-native-guardrails.sh --release
```

For iOS release, archive locally from the SwiftUI workspace only:

```sh
xcodebuild -workspace ios/CALNative.xcworkspace -scheme CALNative -configuration Release archive
```

For Android bridge release, Expo/React Native may be used only for Android until Compose is production approved.

## Release Rule

Native release builds must use a clean Git checkout at a commit already pushed to `origin`. The backend commit required by the native build must already be deployed or explicitly listed in the release notes.
