package com.midfloridasurgical.calcompose.push

import android.content.Context
import android.os.Build
import android.util.Log
import com.midfloridasurgical.calcompose.data.CalApiClient

/**
 * FCM token registration for Compose.
 *
 * **Blocked without Don's Firebase project files:**
 * - `android/app/google-services.json` (missing from repo)
 * - Gradle `com.google.gms.google-services` plugin + Firebase Messaging deps
 *
 * Until those land, this no-ops so `:app:assembleDebug` stays green and Expo
 * (`com.midfloridasurgical.calnative`) is untouched. API client already supports
 * `POST /api/native/push-token` with `provider=fcm`, `platform=android`.
 */
object FcmPushRegistrar {
    private const val TAG = "FcmPushRegistrar"

    /**
     * Returns false when Firebase Messaging is not wired (current state).
     * When `google-services.json` + Firebase deps are added, replace the body
     * with FirebaseMessaging.getInstance().token and [CalApiClient.registerPushToken].
     */
    suspend fun registerIfPossible(
        context: Context,
        apiClient: CalApiClient,
        sessionToken: String,
        deviceToken: String,
    ): Boolean {
        // Keep parameters for the Firebase-wired implementation; silence unused until then.
        Log.i(
            TAG,
            "FCM blocked: missing android/app/google-services.json and Firebase Messaging deps. " +
                "Push registration skipped (alerts UI still works). " +
                "device=${Build.MODEL} apiReady=${apiClient != null} " +
                "session=${sessionToken.isNotBlank()} deviceToken=${deviceToken.isNotBlank()} " +
                "ctx=${context.packageName}",
        )
        return false
    }
}
