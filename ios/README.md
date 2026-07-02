# CAL iOS

This is the imported SwiftUI production iOS lane for CAL.

Current source import: `/Users/donnaile/dev/CAL/cal-native/app/ios`.

Production rule:

- SwiftUI is the only TestFlight lane.
- Build locally from `ios/CALNative.xcodeproj` or the project-only `ios/CALNative.xcworkspace`.
- Do not use React Native or Expo for iOS TestFlight.
- Do not add CocoaPods, Expo, React Native, Node, or generated bundle phases to this iOS target.
- Do not delete the old native worktree until this path has been verified with simulator and archive builds.

Verification:

```sh
xcodebuild -project ios/CALNative.xcodeproj -scheme CALNative -configuration Debug -sdk iphonesimulator -derivedDataPath /tmp/cal-ios-detach-build CODE_SIGNING_ALLOWED=NO build
```
