# CAL Restructure Phase 6 iOS Release Proof

Last updated: 2026-07-01

## Purpose

Phase 6 proves that the new imported pure SwiftUI iOS lane can build, launch, render real CAL UI on the CAL simulator, and produce a signed Release archive from the new repository path.

## Source Path During Phase 6

```text
/Users/donnaile/dev/CAL/cal-app/ios
```

## Active Source Path After Phase 11

```text
/Users/donnaile/dev/CAL/ios
```

Production iOS project:

```text
/Users/donnaile/dev/CAL/ios/CALNative.xcodeproj
```

Scheme:

```text
CALNative
```

Bundle id:

```text
com.midfloridasurgical.calnative
```

## Simulator Proof

Command:

```sh
xcodebuildmcp simulator build-and-run \
  --project-path /Users/donnaile/dev/CAL/ios/CALNative.xcodeproj \
  --scheme CALNative \
  --simulator-id 623FFD67-1A18-4AF2-9EFE-1FD49B7A7808 \
  --configuration Debug \
  --derived-data-path /tmp/cal-ios-phase6-run \
  --prefer-xcodebuild true
```

Result:

```text
iOS simulator build and run succeeded.
The app (com.midfloridasurgical.calnative) is now running in the iOS Simulator.
```

CAL simulator:

```text
CAL (623FFD67-1A18-4AF2-9EFE-1FD49B7A7808)
```

## UI Proof

The running simulator rendered the SwiftUI Schedule screen with:

- Schedule title/menu
- Day / Week / Month segmented control
- Today card
- On Call card
- Off list
- My Schedule card
- Meetings card
- Personal Items card

Captured screenshot path during verification:

```text
/var/folders/8n/mpbzr2h13ps9jgjty501665w0000gn/T/screenshot_optimized_968a252f-48e2-4c2e-969f-1d6af1a8f431.jpg
```

## Release Archive Proof

Command:

```sh
xcodebuild \
  -project ios/CALNative.xcodeproj \
  -scheme CALNative \
  -configuration Release \
  -sdk iphoneos \
  -archivePath /tmp/cal-ios-phase6-archive.xcarchive \
  archive
```

Result:

```text
ARCHIVE SUCCEEDED
```

Signing proof from the archive output:

```text
Signing Identity: iPhone Distribution: Donald Naile Jr (9JJV6C7LD4)
Provisioning Profile: CAL Native Appstore Distribution
Bundle id: com.midfloridasurgical.calnative
```

## What This Proves

- The new `ios/` path is a real build/run source path.
- The app launches on the CAL simulator from the new path.
- The visible UI is SwiftUI CAL, not React Native.
- Release archive signing works with the installed App Store distribution profile.
- TestFlight can now use this cleaned SwiftUI lane for the next upload.

## Remaining Work

- Export the archive to IPA when the next TestFlight push is requested.
- Upload with Transporter/altool after the export.
- Keep `scripts/check-native-guardrails.sh` in the release path before upload.
- Do not reintroduce Expo, React Native, CocoaPods, or Node build phases into `ios/`.
