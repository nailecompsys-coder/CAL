# Phase 12: Release Readiness From Final Root

Date: 2026-07-07

## Goal

Prove the final top-level CAL repo layout is ready for normal app and beta work without falling back into old path drift.

Active Git root:

```text
/Users/donnaile/dev/CAL
```

Production root remains:

```text
/opt/cal
```

## Release Lanes

| Lane | Active source | Release path |
|---|---|---|
| Backend/admin portal/native API | `server/` | Deploy pushed Git commit to `/opt/cal`, verify `/health` |
| iOS | `ios/` | Local SwiftUI Xcode archive/TestFlight |
| Android temporary | `legacy-react-native/` | Expo Android bridge only |
| Android target | `android/` | Jetpack Compose parity work, not production yet |
| Docs/AI context | `docs/`, `.cursor/`, `CLAUDE.md` | Committed with source changes that affect behavior or release paths |

## Commands Proved In This Phase

Run from `/Users/donnaile/dev/CAL`:

```sh
./scripts/check-native-guardrails.sh
./scripts/test-local.sh
docker compose --env-file .env.example config
xcodebuildmcp simulator build --project-path ios/CALNative.xcodeproj --scheme CALNative --configuration Debug --simulator-id 623FFD67-1A18-4AF2-9EFE-1FD49B7A7808 --prefer-xcodebuild
cd android && ./gradlew :app:assembleDebug
npm --prefix legacy-react-native run doctor
```

For release mode after committing and pushing:

```sh
./scripts/check-native-guardrails.sh --release
```

## Decisions

- No production runtime deploy is required for this phase unless runtime source changes are added later.
- iOS TestFlight must come only from `ios/`.
- Android Expo may ship only from `legacy-react-native/` until Compose parity is approved.
- Compose work continues in `android/`, but it is not a production release lane yet.
- Patient/Aprima background service work belongs under `server/` because it is backend data ingestion, not native UI code.

## Exit Criteria

- Root docs no longer point agents or humans at the old nested backend path.
- Guardrails pass from the final root.
- Backend tests pass from the final root.
- Docker Compose config resolves from the final root.
- iOS SwiftUI project builds from `ios/`.
- Android Compose debug build resolves from `android/`.
- Expo bridge doctor runs from `legacy-react-native/`.
- The resulting commit is pushed to `origin/main`.
