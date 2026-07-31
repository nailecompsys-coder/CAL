# CAL Android (Compose)

Jetpack Compose surgeon client. Expo (`legacy-react-native`) remains Lucy’s bridge until cutover.

## Build

```sh
./gradlew :app:assembleDebug
```

## Phase 4 notes — FCM blocker

Client push registration is **blocked** until Don provides Firebase project assets:

1. Place `android/app/google-services.json` (package / `applicationId` must match: debug `com.midfloridasurgical.calcompose`).
2. Add Gradle plugin `com.google.gms.google-services` + Firebase Messaging dependency.
3. Replace the no-op body in `push/FcmPushRegistrar.kt` with `FirebaseMessaging.getInstance().token` → `CalApiClient.registerPushToken(..., provider = "fcm", platform = "android")`.

Server (additive, already wired in this tree):

- `save_push_token` accepts `provider=fcm`.
- `push.py` `_send_fcm_push` (HTTP v1) runs when `FCM_PROJECT_ID` + service account (`FCM_SERVICE_ACCOUNT_PATH` or `FCM_SERVICE_ACCOUNT_JSON`) are set; otherwise send no-ops like missing APNs keys.
- Expo + APNs paths unchanged.

Alerts inbox UI works without FCM (home `alerts` + `POST /api/native/alerts/read`).

## Rules

- Match iOS SwiftUI look + function (`docs/COMPOSE_MIGRATION_PLAN.md`).
- Palette hex only in `ClinicalPalette.kt`.
- Do not disturb Expo qemu / Expo APK workflows.
