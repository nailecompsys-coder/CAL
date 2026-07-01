# CAL Native Local Release Flow

This app is built and verified locally from Xcode/XcodeBuildMCP. Do not use EAS for simulator, archive, or TestFlight work.

## Simulator Verification

Use the local workspace and scheme:

```sh
xcodebuildmcp simulator build-and-run \
  --workspace-path /Users/donnaile/dev/CAL/cal-native/app/ios/CALNative.xcworkspace \
  --scheme CALNative \
  --configuration Debug \
  --simulator-id 623FFD67-1A18-4AF2-9EFE-1FD49B7A7808
```

Expected result: `com.midfloridasurgical.calnative` launches on the CAL simulator.

## Before TestFlight

1. Run `./scripts/check-native-guardrails.sh --release`.
2. Confirm backend `main` is pushed and deployed as needed.
3. Confirm native `native-ios` is pushed.
4. Run the simulator verification command above.
5. Confirm version/build number in Xcode project settings.
6. Archive locally with Xcode or local `xcodebuild`; do not run EAS.

## Current Policy

Only push to TestFlight when explicitly requested. Routine cleanup and simulator validation stop after the local simulator build/run succeeds.

## Stack Guardrails

- SwiftUI under `ios/CALNative` is the only production iOS lane.
- Expo/React Native is a temporary Android bridge, not a TestFlight lane.
- Jetpack Compose is the target Android lane, but it is not production until it has real CAL API integration and parity approval.
- Any native workflow change must update `docs/cal-native-parity-ledger.md` in the same commit.
