package com.midfloridasurgical.calcompose.data

import android.content.Context
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import com.midfloridasurgical.calcompose.data.models.SessionRole

/**
 * Session tokens stay in prefs; [token]/[deviceToken] are only set after OTP sign-in
 * or biometric unlock (mirrors iOS keychain + Face ID gate).
 */
class CalSessionStore(context: Context) {
    private val preferences =
        context.getSharedPreferences(PREFERENCES_NAME, Context.MODE_PRIVATE)

    /** Active session — null until OTP save or [unlockStoredSession]. */
    var token by mutableStateOf<String?>(null)
        private set

    var deviceToken by mutableStateOf<String?>(null)
        private set

    var role by mutableStateOf(
        SessionRole.fromStoredValue(preferences.getString(KEY_ROLE, null)),
    )
        private set

    /** Skip biometric and show OTP when user chose "Use OTP". */
    var preferOtp by mutableStateOf(false)

    val hasStoredSession: Boolean
        get() {
            val stored = preferences.getString(KEY_TOKEN, null)
            val storedDevice = preferences.getString(KEY_DEVICE_TOKEN, null)
            return !stored.isNullOrBlank() && !storedDevice.isNullOrBlank()
        }

    fun saveSession(
        token: String,
        deviceToken: String = token,
        role: SessionRole = SessionRole.SURGEON,
    ) {
        preferences.edit()
            .putString(KEY_TOKEN, token)
            .putString(KEY_DEVICE_TOKEN, deviceToken)
            .putString(KEY_ROLE, role.storedValue)
            .apply()
        this.token = token
        this.deviceToken = deviceToken
        this.role = role
        preferOtp = false
    }

    /** Load prefs into active session after biometric success. */
    fun unlockStoredSession(): Boolean {
        val stored = preferences.getString(KEY_TOKEN, null)
        val storedDevice = preferences.getString(KEY_DEVICE_TOKEN, null)
        if (stored.isNullOrBlank() || storedDevice.isNullOrBlank()) return false
        token = stored
        deviceToken = storedDevice
        role = SessionRole.fromStoredValue(preferences.getString(KEY_ROLE, null))
        preferOtp = false
        return true
    }

    fun clear() {
        preferences.edit().clear().apply()
        token = null
        deviceToken = null
        role = SessionRole.SURGEON
        preferOtp = false
    }

    private companion object {
        const val PREFERENCES_NAME = "cal_session"
        const val KEY_TOKEN = "token"
        const val KEY_DEVICE_TOKEN = "device_token"
        const val KEY_ROLE = "role"
    }
}
