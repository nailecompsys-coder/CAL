# CAL Restructure Phase 10 Workspace Quarantine

Phase 10 makes the correct local development paths explicit and marks stale outer workspace folders as retired without deleting them.

## Active Git Root

```text
/Users/donnaile/dev/CAL/cal-app
```

This remains the only active Git repository for CAL production work.

## Active Lanes

| Lane | Active path | Notes |
| --- | --- | --- |
| Backend/admin portal/native API | `server/` | Production deploy source |
| iOS SwiftUI | `ios/` | TestFlight lane |
| Android Compose | `android/` | Target Android lane |
| Android Expo bridge | `legacy-react-native/` | Temporary Android bridge only |
| Docs/AI | `docs/` | Tracked operational docs |
| Guard/orchestration scripts | `scripts/` | Cross-lane safety checks and compatibility wrappers |

## Quarantined Outer Folders

The following folders exist outside the active Git root and are now marked with local `DO_NOT_EDIT...` files:

| Outer path | Status | Reason |
| --- | --- | --- |
| `/Users/donnaile/dev/CAL/cal-native` | Retired/reference only | Old native workspace; `app/` contains nested Git state and local `.env` |
| `/Users/donnaile/dev/CAL/android-compose-prototype` | Retired/reference only | Compose source was imported to `cal-app/android` |
| `/Users/donnaile/dev/CAL/docs` | Retired/reference only | Loose docs were imported to `cal-app/docs/imported/top-level` |
| `/Users/donnaile/dev/CAL/cursor` | Retired/reference only | AI context imported to `cal-app/docs/ai` |
| `/Users/donnaile/dev/CAL/cal-web` | Retired/reference only | Placeholder imported to `cal-app/docs/imported/web-placeholder` |

## Important Findings

- The outer `/Users/donnaile/dev/CAL` folder is not a Git repository.
- `/Users/donnaile/dev/CAL/cal-app` is the active Git root.
- The old `/Users/donnaile/dev/CAL/cal-native/app` nested Git checkout still exists, but it is no longer an active production lane.
- The loose outer `docs/` folder matches the imported tracked docs.
- No production runtime files were deleted in this phase.

## Current Commands

Backend tests:

```sh
cd /Users/donnaile/dev/CAL/cal-app
./scripts/test-local.sh
```

Backend production deploy:

```sh
cd /opt/cal
NO_BUMP=1 CAL_STANDALONE=1 ./server/scripts/rebuild-cal-api.sh
```

iOS source:

```text
/Users/donnaile/dev/CAL/cal-app/ios
```

Android Compose source:

```text
/Users/donnaile/dev/CAL/cal-app/android
```

## Next Phase Recommendation

Phase 11 should decide whether to physically promote `cal-app` contents into `/Users/donnaile/dev/CAL` as the top-level Git root, or keep `cal-app` as the permanent repository root and archive the retired outer folders.

Do not combine Phase 11 with app feature work, TestFlight, Expo release, or Aprima worker implementation.
