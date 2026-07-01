# CAL Restructure Phase 2 Target Layout

Last updated: 2026-07-01

## Purpose

Phase 2 defines the destination filesystem, Git strategy, naming rules, and migration order. It does not move production code yet. Later phases must follow this document unless a replacement plan is explicitly approved.

## Target Top-Level Layout

Future local root:

```text
/Users/donnaile/dev/CAL/
  server/
  ios/
  android/
  legacy-react-native/
  docs/
  ai/
  scripts/
  archive/
```

The goal is for `/Users/donnaile/dev/CAL` to become the single Git root after migration, instead of having separate Git worktrees under `cal-app` and `cal-native/app`.

## Directory Ownership

| Target folder | Owns | Must not own |
|---|---|---|
| `server/` | FastAPI, admin portal, surgeon web/PWA, native APIs, database models, deploy scripts, backend tests, Aprima integration | SwiftUI app source, Android app source, AI working notes |
| `ios/` | SwiftUI iPhone app, Xcode project/workspace, iOS assets, iOS release scripts/docs | React Native app, Android code, backend server code |
| `android/` | Jetpack Compose Android app, Gradle project, Android release scripts/docs | Expo app, SwiftUI app, backend server code |
| `legacy-react-native/` | Temporary Expo/React Native Android bridge | iOS TestFlight production lane, long-term Android source of truth |
| `docs/` | Architecture, runbooks, release checklists, parity ledger, Aprima policy, production docs | Secrets, PHI, throwaway AI notes |
| `ai/` | Agent context, AI prompts, review notes, temporary planning context | Runtime code, production config, secrets |
| `scripts/` | Top-level guard/check/orchestration scripts that coordinate multiple folders | Server-only deploy internals that belong in `server/scripts` |
| `archive/` | Deprecated docs or retired source kept for historical reference | Active production code |

## Source Mapping

| Current path | Target path | Move phase | Notes |
|---|---|---:|---|
| `cal-app/` | `server/` | Last | Production depends on this path today; move only after native/docs cleanup |
| `cal-native/app/ios/CALNative*` | `ios/` | Native phase | SwiftUI becomes clean iOS lane |
| `cal-native/app/ios/Podfile*` | `ios/` | Native phase | Keep CocoaPods with iOS workspace if still required |
| `cal-native/app/App.tsx`, `src/`, `package*.json`, `app.json`, `eas.json` | `legacy-react-native/` | Native phase | Android bridge only; no TestFlight lane |
| `android-compose-prototype/` | `android/` | Native phase | Rename from prototype only after Gradle build still works |
| `cal-app/docs/` | `docs/server/` or `docs/` | Docs phase | Keep high-value docs; remove duplicates later |
| `cal-native/app/docs/` | `docs/native/` | Docs phase | Release docs and native guardrails |
| `cal-native/docs/` | `docs/native/legacy/` | Docs phase | Review before keeping |
| top-level `docs/` | `docs/` | Docs phase | Merge with canonical docs |
| `cursor/` | `ai/` | Docs/AI phase | AI context only |
| `cal-web/` | `archive/cal-web-placeholder/` | Cleanup phase | Placeholder only unless later reused |
| `IMG_2565.png` | `ios/` assets and/or `docs/assets/` | Native/docs phase | Current iPhone icon source asset |

## Naming Decisions

- Use `server/`, not `backend/`, because the admin portal and surgeon web/PWA live there.
- Use lowercase directory names: `server`, `ios`, `android`, `docs`, `ai`, `scripts`.
- Keep `legacy-react-native/` explicit so nobody mistakes it for the long-term Android lane.
- Do not name the Android Compose folder `expo`; Compose is not Expo.
- Do not place Aprima at top level unless it becomes a separate deployable service later.

## Git Strategy

Target: one Git repository rooted at:

```text
/Users/donnaile/dev/CAL
```

Rules:

- Preserve history as much as practical, but production safety is more important than perfect history.
- No production deploy should run from an unpushed local commit.
- No release should build from dirty working state.
- Existing `cal-app/main` remains the production source until the final server move is complete.
- Existing `cal-native/app/native-ios` remains the native release source until iOS has moved and built from `ios/`.
- Do not delete old worktrees until the new root repo can build server and iOS locally.

## Production Path Strategy

Current production path remains:

```text
/opt/cal
```

After the server move, production should still clone/pull to `/opt/cal`, but app code will live under:

```text
/opt/cal/server/
```

That means production deploy scripts must be updated from assumptions like:

```text
/opt/cal/app/main.py
/opt/cal/scripts/rebuild-cal-api.sh
```

to:

```text
/opt/cal/server/app/main.py
/opt/cal/server/scripts/rebuild-cal-api.sh
```

Do not change `/opt/cal` itself unless separately approved. Changing the inside layout is enough.

## iOS Build Path Strategy

Current iOS TestFlight path:

```text
/Users/donnaile/dev/CAL/cal-native/app/ios/CALNative.xcworkspace
```

Target iOS path:

```text
/Users/donnaile/dev/CAL/ios/CALNative.xcworkspace
```

Rules:

- SwiftUI remains the only production iOS lane.
- TestFlight must build locally from `ios/`.
- React Native iOS remains blocked unless explicitly marked experimental.
- The native release doc must be updated in the same commit as the move.

## Android Build Path Strategy

Temporary Android bridge target:

```text
/Users/donnaile/dev/CAL/legacy-react-native/
```

Target Android production lane:

```text
/Users/donnaile/dev/CAL/android/
```

Rules:

- Expo/React Native can continue only as a temporary Android bridge.
- Jetpack Compose becomes production only after real API integration and parity approval.
- Android must match SwiftUI screens and workflows unless the parity ledger documents a temporary gap.

## Aprima Placement Strategy

Aprima belongs in the server integration layer:

```text
server/app/integrations/aprima/
server/app/workers/aprima_worker.py
```

Do not put Aprima code in `ios/`, `android/`, or `legacy-react-native/`.

Future worker container may be:

```text
cal_worker_aprima
```

But that is a later implementation step, not part of filesystem restructure.

## Migration Order

Follow this order exactly:

1. Inventory current state. Completed in Phase 1.
2. Define target layout. This document.
3. Consolidate docs and AI notes.
4. Move native lanes:
   - SwiftUI to `ios/`
   - Compose to `android/`
   - Expo/React Native to `legacy-react-native/`
5. Verify native builds from new paths.
6. Move `cal-app/` to `server/`.
7. Update local server scripts and tests.
8. Update production deploy scripts.
9. Pull/deploy from the new root layout on production.
10. Implement Aprima background service after the layout is stable.

## Guardrails For Later Phases

- Do not combine server move and Aprima worker implementation in the same commit.
- Do not combine iOS move and server production deploy in the same commit.
- Do not remove old folders until the new path has passed its build/test gate.
- Do not move secrets into Git.
- Do not commit PHI, SQL dumps, local `.env`, archives, APKs, IPAs, DerivedData, `.expo`, or `node_modules`.
- Keep rollback path obvious at each phase.

## Acceptance Criteria For Phase 2

- Target layout documented.
- Current-to-target path map documented.
- Production path strategy documented.
- iOS/TestFlight path strategy documented.
- Android strategy documented.
- Aprima placement documented.
- Migration order documented.
- No code folders moved.
- No production runtime changed.
- Phase 2 document committed and pushed.
