# CAL Restructure Phase 5 iOS SwiftUI Detach

Last updated: 2026-07-01

## Purpose

Phase 5 makes the imported `ios/` lane a true SwiftUI production iOS app. The TestFlight path no longer depends on Expo, React Native, CocoaPods, Node, generated Expo providers, or React Native bundle build phases.

## What Changed

- Replaced the Expo/RN `AppDelegate` bootstrap with a pure SwiftUI `@main` app entry.
- Removed CocoaPods build configuration references from `ios/CALNative.xcodeproj`.
- Removed Expo and React Native Xcode script phases.
- Removed Expo provider and `Expo.plist` project references.
- Removed Pod files and the Node `.xcode.env` file from the imported iOS lane.
- Updated `ios/CALNative.xcworkspace` so it references only `CALNative.xcodeproj`.
- Added guardrail checks that fail if the production iOS lane regains Podfile, Expo support, or Node Xcode environment files.

## Verification

This simulator build passes from the imported production path:

```sh
xcodebuild -project ios/CALNative.xcodeproj -scheme CALNative -configuration Debug -sdk iphonesimulator -derivedDataPath /tmp/cal-ios-detach-build CODE_SIGNING_ALLOWED=NO build
```

Result:

```text
BUILD SUCCEEDED
```

## Remaining Release Work

- Run a Release archive check before the next TestFlight upload.
- Verify app launch on the CAL simulator from `ios/`.
- Keep the old `/Users/donnaile/dev/CAL/cal-native/app` worktree untouched until the new iOS path has simulator and archive release proof.
- Continue using `legacy-react-native/` only as the temporary Android bridge until Compose is backend-integrated.

## Acceptance Criteria

- `ios/` builds without Pods installed.
- No React Native or Expo import remains in `ios/CALNative`.
- No CocoaPods or React Native build phase remains in the Xcode target.
- Guardrails pass.
- Backend tests pass.
- Commit pushed to `main`.
