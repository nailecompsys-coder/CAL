# CAL Native Stack Guardrails

Last updated: 2026-07-07

## Decision

SwiftUI is the production iOS app. Jetpack Compose is the target Android app. Expo/React Native is the temporary Android bridge only until Compose reaches parity. React Native iOS is not a production lane.

## Production Lanes

| Lane | Source | Status | Release Rule |
|---|---|---|---|
| Backend/API | `server/` | Production source of truth | API changes must preserve web and native contracts |
| iOS | `ios/` | Production/TestFlight lane | Only pure SwiftUI builds may ship to TestFlight |
| Android temporary | `legacy-react-native/` | Expo/React Native bridge | Android-only bridge until Compose is ready |
| Android target | `android/` | Compose target lane | Not production until real API integration and parity approval |

## Non-Negotiable Rules

- No native client may invent workflow behavior that is not backed by a documented backend endpoint and a backend contract test.
- Any native source change must update `docs/cal-native-parity-ledger.md` in the same commit unless it is a pure comment or formatting-only change.
- Any backend endpoint used by native clients must have a contract test under `server/tests/test_native_*.py` or a directly related auth/push test.
- React Native iOS builds are experimental only and must not be sent to TestFlight.
- The imported `ios/` production lane must not contain `Podfile`, `.xcode.env`, Expo support files, React Native bundle phases, or CocoaPods build settings.
- The `legacy-react-native/` bridge must remain Android-only. It must not define Expo iOS config, iOS EAS profiles, or TestFlight scripts.
- Android must match the SwiftUI screen and workflow unless the parity ledger marks a temporary approved gap.
- Build artifacts, dependency folders, local Expo state, Xcode archives, IPAs, APKs, and DerivedData must not be staged or tracked.

## Required Preflight Commands

From `/Users/donnaile/dev/CAL` before backend deploy:

```sh
./scripts/check-native-guardrails.sh --release
./scripts/test-local.sh
```

From `/Users/donnaile/dev/CAL` before Android handoff:

```sh
./scripts/check-native-guardrails.sh --release
npm --prefix legacy-react-native ci
npm --prefix legacy-react-native run doctor
cd android && ./gradlew :app:assembleDebug
```

For iOS release, archive locally from the SwiftUI Xcode project:

```sh
xcodebuildmcp simulator build \
  --project-path ios/CALNative.xcodeproj \
  --scheme CALNative
```

For Android bridge release, Expo/React Native may be used only for Android until Compose is production approved.

## Production Deploy Rule

Production deploys must use a clean Git checkout at a commit already pushed to `origin`. After deploy, verify:

```sh
curl -sf https://cal.midfloridasurgical.com/health
git rev-parse HEAD
```

The deployed `/health` version must match the expected backend build, and the server checkout must match the pushed commit being deployed.
