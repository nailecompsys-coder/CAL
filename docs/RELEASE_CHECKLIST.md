# CAL Release Checklist

Last updated: 2026-07-07

Use this before any backend deploy, TestFlight build, or Android handoff. The goal is to keep local, Git, production, TestFlight, and Android release lanes from drifting.

## 1. Confirm Workspace

```sh
cd /Users/donnaile/dev/CAL
git status --short
git rev-parse --show-toplevel
git rev-parse --short HEAD
```

Expected Git root:

```text
/Users/donnaile/dev/CAL
```

Do not release from retired folders under `/Users/donnaile/dev/CAL-retired-20260707`.

## 2. Run Required Local Gates

```sh
./scripts/check-native-guardrails.sh
./scripts/test-local.sh
make doctor
docker compose --env-file .env.example config
```

Before a production deploy, commit and push first, then run:

```sh
./scripts/check-native-guardrails.sh --release
```

## 3. Backend/Admin Portal Deploy Gate

Backend/admin portal source is `server/`.

Only deploy an exact commit already pushed to `origin/main`.

Before deploy:

```sh
git status --short
git rev-parse HEAD
git rev-parse origin/main
```

After deploy, verify:

```sh
curl -sf https://cal.midfloridasurgical.com/health
```

The reported version must match `server/VERSION` for the deployed commit.

## 4. iOS TestFlight Gate

iOS production source is `ios/`.

React Native iOS is not a production lane.

Build proof:

```sh
xcodebuildmcp simulator build \
  --project-path ios/CALNative.xcodeproj \
  --scheme CALNative \
  --configuration Debug \
  --simulator-id 623FFD67-1A18-4AF2-9EFE-1FD49B7A7808 \
  --prefer-xcodebuild
```

If that simulator is missing, list simulators with `xcodebuildmcp simulator list` and use the local CAL simulator id.

For TestFlight, archive from the SwiftUI Xcode project under `ios/` only. Update the iOS build badge/version in the same commit as the release change.

## 5. Android Gate

Temporary Android bridge source is `legacy-react-native/`.

```sh
npm --prefix legacy-react-native run doctor
```

Jetpack Compose target source is `android/`.

```sh
cd android
./gradlew :app:assembleDebug
```

Compose is not a production release lane until the parity ledger marks auth, today, schedule, time off, on-call, patients, and push behavior production-ready.

## 6. Parity And Contract Rules

- Native UI or workflow changes must update `docs/cal-native-parity-ledger.md`.
- Native API/backend behavior changes must update or add tests under `server/tests/test_native_*.py`, `server/tests/test_surgeon_otp_*.py`, or `server/tests/test_push_*.py`.
- Patient/Aprima changes must stay read-only against Aprima SQL and belong under `server/`.
- No build artifacts, APKs, IPAs, archives, `node_modules`, `.expo`, Gradle caches, or DerivedData may be committed.

## 7. Beta Exit Gate

Before removing beta language or calling CAL production-ready:

- Backend health and version are verified after deploy.
- iOS TestFlight build number is current.
- Android users have either approved Expo bridge behavior or approved Compose parity.
- OTP sign-in works by email and phone.
- Patient schedule data is verified against Aprima source times.
- Admin portal critical flows work: calendar, call schedule, days off, physicians, locations, metrics, settings, backup status.
