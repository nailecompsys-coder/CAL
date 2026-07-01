# CAL Restructure Phase 4 Native Lane Import

Last updated: 2026-07-01

## Purpose

Phase 4 imports native source into the tracked production Git repository using the target lane names from Phase 2. This phase is an import, not a destructive move. The old native folders remain in place until the new paths pass their build gates.

## Imported Lanes

| Lane | Imported from | Imported to | Status |
|---|---|---|---|
| iOS SwiftUI | `/Users/donnaile/dev/CAL/cal-native/app/ios` | `ios/` | Production iOS lane, pending build verification from new path |
| Android Compose | `/Users/donnaile/dev/CAL/android-compose-prototype` | `android/` | Target Android lane, still not production |
| Expo / React Native | `/Users/donnaile/dev/CAL/cal-native/app` excluding `ios/` | `legacy-react-native/` | Temporary Android bridge only |

The imported `legacy-react-native/` copy removes iOS/TestFlight npm and EAS release scripts. React Native iOS remains blocked; SwiftUI under `ios/` is the only iOS production lane.

## What Was Not Moved

No old source folders were deleted or renamed:

```text
/Users/donnaile/dev/CAL/cal-native/app
/Users/donnaile/dev/CAL/android-compose-prototype
```

No production server files were moved. Production still runs from `/opt/cal` with server files at the current root layout.

## New Local Build Paths

Future iOS path:

```text
/Users/donnaile/dev/CAL/cal-app/ios/CALNative.xcworkspace
```

Future Android Compose path:

```text
/Users/donnaile/dev/CAL/cal-app/android
```

Temporary Android bridge path:

```text
/Users/donnaile/dev/CAL/cal-app/legacy-react-native
```

These paths become final only after simulator/build verification passes and later phases move the top-level Git root.

## Guardrail Updates

`scripts/check-native-guardrails.sh` now checks imported native paths in `cal-app`:

```text
ios/
android/
legacy-react-native/
```

Native source or build metadata changes in these folders require a parity ledger or guardrail doc update in the same commit.

## Next Required Verification

Before deleting or retiring old native folders:

1. Build/run SwiftUI from `ios/CALNative.xcworkspace`.
2. Build Android Compose from `android/`.
3. Confirm Expo bridge can still be built from `legacy-react-native/` if it is needed for Android release.
4. Update release docs to point at the new paths.
5. Only then remove old duplicate folders in a later cleanup phase.

## Verification Results During Import

- `xcodebuild -workspace ios/CALNative.xcworkspace -list` succeeds and finds scheme `CALNative`.
- `xcodebuild ... build` from imported `ios/` currently fails because `ios/Pods/Target Support Files/Pods-CALNative/Pods-CALNative.debug.xcconfig` is not present. Pods are intentionally not tracked.
- The imported iOS app still imports Expo/React support in `AppDelegate.swift` and Xcode build phases. That must be cleaned up or redirected before the old native worktree is retired.
- `./gradlew :app:assembleDebug` succeeds from imported `android/`.
- `legacy-react-native/` package metadata is readable, and iOS/TestFlight scripts were removed from the imported bridge copy.

## Follow-Up Required Before Old Native Folder Removal

The next native cleanup must decide one of these paths for iOS:

1. Fully detach SwiftUI iOS from Expo/React Native support, removing Expo/RN AppDelegate hooks, Pods, and build phases.
2. Keep Expo/RN support temporarily, but explicitly point CocoaPods and Xcode scripts at `legacy-react-native/` dependencies.

Option 1 is the preferred production direction because SwiftUI is the production iOS lane and React Native iOS is blocked.

## Acceptance Criteria

- Native source imported into tracked lane folders.
- Old folders preserved.
- Guardrails updated for imported paths.
- No production server move.
- No production runtime rebuild.
- Backend tests pass.
- Guardrails pass.
- Commit pushed to `main`.
