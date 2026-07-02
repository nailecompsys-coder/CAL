# CAL Legacy React Native Bridge

This is the imported Expo/React Native temporary bridge.

Current source import: `/Users/donnaile/dev/CAL/cal-native/app` excluding the SwiftUI `ios/` folder.

Production rule:

- This lane is temporary.
- It may be used for Android bridge releases only while Jetpack Compose is incomplete.
- It is not the production iOS/TestFlight lane.
- New long-term Android work belongs in `android/`, not here.
- Do not add an Expo `ios` config, iOS EAS profile, or TestFlight script here. SwiftUI under `ios/` is the only iOS lane.

Verification:

```sh
npm ci
npm run doctor
```
