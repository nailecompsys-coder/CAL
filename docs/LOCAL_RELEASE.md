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

1. Confirm backend `main` is pushed and deployed as needed.
2. Confirm native `native-ios` is pushed.
3. Run the simulator verification command above.
4. Confirm version/build number in Xcode project settings.
5. Archive locally with Xcode or local `xcodebuild`; do not run EAS.

## Current Policy

Only push to TestFlight when explicitly requested. Routine cleanup and simulator validation stop after the local simulator build/run succeeds.
