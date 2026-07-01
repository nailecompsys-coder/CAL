# CAL Restructure Phase 1 Inventory

Last updated: 2026-07-01

## Purpose

This is the ground-truth inventory before any folder moves. Phase 1 does not move code, change production runtime paths, change TestFlight paths, or change Aprima behavior. It records the current state so later cleanup can be done without losing rollback paths.

## Current Local Layout

`/Users/donnaile/dev/CAL` is a container folder, not a Git repository.

```text
/Users/donnaile/dev/CAL/
  cal-app/                    # production FastAPI/server/admin portal Git worktree
  cal-native/
    app/                      # native Git worktree: Expo + SwiftUI iOS
    docs/                     # native docs outside the native Git worktree
  android-compose-prototype/  # Jetpack Compose prototype, not currently a Git worktree
  cal-web/                    # placeholder only
  docs/                       # top-level docs, not currently in Git
  cursor/                     # AI/Cursor context, not currently in Git
  IMG_2565.png                # CAL app icon asset at top level
```

## Current Git Worktrees

| Local path | Branch | Current commit | Remote |
|---|---:|---|---|
| `/Users/donnaile/dev/CAL/cal-app` | `main` | `0a5f68176ea3c21754d0cc60fb2e629833cba804` | `git@github.com:nailecompsys-coder/CAL.git` |
| `/Users/donnaile/dev/CAL/cal-native/app` | `native-ios` | `9c3672ae1f5967cb9f1647e8631b98fd634b1abd` | `git@github.com:nailecompsys-coder/CAL.git` |
| `/Users/donnaile/dev/CAL/android-compose-prototype` | none | not a Git repo | none |

Important: `cal-app` and `cal-native/app` are separate local Git worktrees pointing at the same remote repository but different branches. This is a drift risk and is one of the main reasons for the restructure.

## Current Production State

| Item | Current value |
|---|---|
| Production VM alias | `cal-5.62` |
| Production path | `/opt/cal` |
| Production branch | `main` |
| Production commit | `0a5f68176ea3c21754d0cc60fb2e629833cba804` |
| Public host | `https://cal.midfloridasurgical.com` |
| Health response | `{"status":"ok","version":"1.3.5-beta.1+20260701T120527Z"}` |

Current production expects server files directly under `/opt/cal`, for example:

```text
/opt/cal/app/main.py
/opt/cal/scripts/rebuild-cal-api.sh
/opt/cal/docker-compose.standalone.yml
```

Any future move from `cal-app/` to `server/` must update production scripts and compose paths deliberately. Do not move server files first.

## Current Server / Portal Scope

`cal-app` currently contains all of these responsibilities:

- FastAPI application runtime.
- Admin portal web pages.
- Surgeon web/PWA pages.
- Native JSON APIs.
- Database models.
- Startup migration modules.
- Backup/restore scripts.
- Docker and production deploy scripts.
- Tests.
- Some docs.

Current key paths:

```text
cal-app/app/main.py
cal-app/app/models.py
cal-app/app/routers/
cal-app/app/templates/
cal-app/scripts/
cal-app/tests/
cal-app/docs/
```

Plain-English naming: this is better described as `server/` than only `backend/`, because the portal web app lives here too.

## Current iOS State

SwiftUI iOS production source currently lives inside the Expo/native worktree:

```text
cal-native/app/ios/CALNative/
cal-native/app/ios/CALNative.xcworkspace
cal-native/app/ios/CALNative.xcodeproj
```

Current iOS release facts:

- Bundle identifier: `com.midfloridasurgical.calnative`
- App version: `1.0.1`
- iOS build number: `12`
- Current local TestFlight build path:

```text
/Users/donnaile/dev/CAL/cal-native/app/ios/CALNative.xcworkspace
```

Current policy:

- Build iOS locally from Xcode/XcodeBuildMCP.
- Do not use EAS for iOS TestFlight.
- SwiftUI is the only production iOS lane.
- React Native iOS is not a production lane.

## Current Android State

There are two Android-related paths:

```text
cal-native/app/                 # Expo/React Native temporary Android bridge
android-compose-prototype/      # Jetpack Compose prototype
```

Current Expo/React Native Android facts:

- Package: `com.midfloridasurgical.calnative`
- Version: `1.0.1`
- Android version code: `10`
- Expo project ID: `98f62090-f436-49c5-b758-07f371011061`

Current Jetpack Compose facts:

- Path: `/Users/donnaile/dev/CAL/android-compose-prototype`
- Gradle project name: `CALComposePrototype`
- Application ID: `com.midfloridasurgical.calcompose`
- Version name/code: `0.1` / `1`
- Current status: prototype only, no real CAL backend integration yet.

Policy:

- Expo/React Native is temporary Android bridge only.
- Jetpack Compose is the target Android production lane.
- Compose cannot become production until it uses real CAL auth, schedule, time off, on-call, patient schedule, and push APIs.

## Current Docs / AI State

Docs are split across multiple places:

```text
cal-app/docs/                  # docs tracked on cal-app/main
cal-native/app/docs/           # docs tracked on native-ios
cal-native/docs/               # outside native Git worktree
/Users/donnaile/dev/CAL/docs/  # outside Git
/Users/donnaile/dev/CAL/cursor # outside Git AI context
```

This is another drift risk. Later phases should consolidate docs into a single top-level `docs/` folder after the Git root strategy is decided.

## Current Aprima State

Aprima patient schedule is currently an on-demand server-side read used by the native patient endpoint.

Current paths:

```text
cal-app/app/native_patient_schedule_service.py
cal-app/app/routers/native_api.py
cal-app/tests/test_native_patient_schedule.py
```

Current behavior:

- Endpoint: `GET /api/native/patient-schedule`
- Reads Aprima through `APRIMA_CONNECTION_STRING`.
- Uses `pymssql`.
- Converts Aprima UTC datetimes to Eastern display times.
- Filters canceled, inactive, recall, possible, and waitlist-like rows.
- Returns live query results directly to the requesting native client.

Target future behavior:

```text
Aprima SQL Server
  -> read-only scheduled poller
  -> CAL database cache
  -> CAL APIs
  -> iOS / Android / Portal
  -> schedule alerts / push notifications
```

Aprima must become a protected server integration area later:

```text
server/app/integrations/aprima/
server/app/workers/aprima_worker.py
```

Hard Aprima rules:

- CAL must only use a read-only Aprima SQL account.
- CAL must never write to Aprima.
- CAL must never alter Aprima schema.
- CAL must never run user-provided SQL.
- CAL must never log patient names, MRNs, DOBs, phone numbers, notes, or appointment details.
- Push notifications must not contain PHI.
- Phones must read CAL cache, not Aprima directly, after the worker is built.

## Existing Guardrails

Guardrail scripts now exist in both active Git worktrees:

```text
cal-app/scripts/check-native-guardrails.sh
cal-native/app/scripts/check-native-guardrails.sh
```

Current guardrail behavior:

- Blocks release mode if repos are dirty or local commits are not pushed.
- Blocks native source changes without parity ledger/guardrail docs.
- Blocks backend native API/auth/push changes without native contract tests.
- Blocks staged/tracked build artifacts such as `node_modules`, `.expo`, `build`, `.xcarchive`, `.ipa`, `.apk`, and DerivedData.

## Current Tests

`cal-app` currently has 21 test files and the local test suite currently runs 58 tests.

Required before later restructure phases:

```sh
cd /Users/donnaile/dev/CAL/cal-app
./scripts/check-native-guardrails.sh --release
./scripts/test-local.sh
```

Required before native release:

```sh
cd /Users/donnaile/dev/CAL/cal-native/app
./scripts/check-native-guardrails.sh --release
```

## Proposed Target Layout

Target layout for later phases:

```text
/Users/donnaile/dev/CAL/
  server/                 # FastAPI, admin portal, surgeon web/PWA, APIs, deploy, tests
  ios/                    # SwiftUI iPhone app only
  android/                # Jetpack Compose Android app only
  legacy-react-native/    # temporary Expo Android bridge until Compose replaces it
  docs/                   # production docs, architecture, release checklists, parity ledger
  ai/                     # AI context, prompts, working notes
  scripts/                # top-level guard/check helpers, if needed
```

## Phase 1 No-Move Rule

Phase 1 does not move or rename any folders.

Do not move:

- `cal-app`
- `cal-native/app`
- `android-compose-prototype`
- `/opt/cal`
- iOS workspace/project files
- Docker/compose files

The next safe phase is docs/AI consolidation planning, then native lane movement, then server movement last.

## Phase 1 Acceptance Criteria

- Current production Git SHA recorded.
- Current production health recorded.
- Current local Git worktrees recorded.
- Current iOS TestFlight path recorded.
- Current Android/Expo and Compose status recorded.
- Current Aprima on-demand integration recorded.
- No code folders moved.
- No production runtime changed.
- Inventory committed and pushed to Git.
