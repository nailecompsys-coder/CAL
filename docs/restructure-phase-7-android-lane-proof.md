# CAL Restructure Phase 7 Android Lane Proof

Last updated: 2026-07-01

## Purpose

Phase 7 proves the Android lanes are separated after the native import:

- `android/` is the Jetpack Compose target lane.
- `legacy-react-native/` is the temporary Expo Android bridge.
- Expo/React Native must not become an iOS/TestFlight lane again.

## Lane Status

| Lane | Path | Package | Status |
|---|---|---|---|
| Android Compose target | `android/` | `com.midfloridasurgical.calcompose` | Buildable prototype, not production |
| Android Expo bridge | `legacy-react-native/` | `com.midfloridasurgical.calnative` | Temporary Android release lane |
| iOS SwiftUI | `ios/` | `com.midfloridasurgical.calnative` | Only TestFlight lane |

## Changes

- Removed the Expo `ios` target config from `legacy-react-native/app.json`.
- Changed the Expo bridge push-token fallback platform from `ios` to `android`.
- Added `expo-doctor` as a local dev dependency so the bridge health check is repeatable.
- Aligned Expo SDK 55 patch dependencies using `npx expo install`.
- Added guardrails that fail if the Expo bridge regains iOS config, iOS EAS profiles, or TestFlight scripts.
- Added Android verification commands to the lane READMEs.

## Compose Verification

Command:

```sh
cd android
./gradlew :app:assembleDebug
```

Result:

```text
BUILD SUCCESSFUL
```

Compose remains a prototype because it does not yet implement real CAL API auth, schedule, time off, on-call, patients, or push behavior.

## Expo Bridge Verification

Command:

```sh
cd legacy-react-native
npm ci
npm run doctor
```

Result:

```text
added 618 packages
Running 19 checks on your project...
19/19 checks passed. No issues detected!
```

`npm ci`/`expo install` reported dependency audit issues from the Expo dependency tree:

```text
14 vulnerabilities (1 low, 11 moderate, 1 high, 1 critical)
```

Those are recorded but not mass-upgraded in this phase because this lane is temporary and broad upgrades can break Expo compatibility. The next Android release should still weigh this before sending a production APK.

## Guardrails

`scripts/check-native-guardrails.sh` now blocks:

- `legacy-react-native/app.json` containing an Expo `ios` target.
- `legacy-react-native/package.json` containing `ios` or `testflight` scripts.
- `legacy-react-native/eas.json` containing iOS/TestFlight release behavior.

## Remaining Work

- If an Android device/emulator is available, run the Expo bridge on Android for visual proof.
- Do not invest in major Expo UI refactors except emergency Android parity fixes; long-term Android work belongs in Compose.
- Begin Compose backend integration only after the server layout move is stable.
