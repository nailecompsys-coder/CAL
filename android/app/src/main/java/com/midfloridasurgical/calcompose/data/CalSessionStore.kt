package com.midfloridasurgical.calcompose.data

import android.content.Context
import android.content.SharedPreferences
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.security.crypto.EncryptedSharedPreferences
import androidx.security.crypto.MasterKey
import com.midfloridasurgical.calcompose.data.models.OtpVerifyResponse
import com.midfloridasurgical.calcompose.data.models.SessionRole

/**
 * Encrypted session store (Android Keystore-backed) mirroring iOS Keychain + Face ID gate.
 * Active [token]/[deviceToken] stay null until OTP sign-in or [unlockStoredSession].
 */
class CalSessionStore(context: Context) {
    private val preferences: SharedPreferences = createSecurePreferences(context)

    /** Active session — null until OTP save or [unlockStoredSession]. */
    var token by mutableStateOf<String?>(null)
        private set

    var deviceToken by mutableStateOf<String?>(null)
        private set

    var role by mutableStateOf(
        SessionRole.fromStoredValue(preferences.getString(KEY_ROLE, null)),
    )
        private set

    var availableRoles by mutableStateOf(readAvailableRoles())
        private set

    /** Skip biometric and show OTP when user chose "Use OTP". */
    var preferOtp by mutableStateOf(false)

    val hasStoredSession: Boolean
        get() {
            val stored = preferences.getString(KEY_TOKEN, null)
            return !stored.isNullOrBlank()
        }

    fun saveFromVerify(response: OtpVerifyResponse) {
        val parsedRoles = response.roles.mapNotNull { raw ->
            SessionRole.entries.firstOrNull { it.storedValue == raw }
        }
        val surgeonToken = response.tokens.surgeon?.takeIf { it.isNotBlank() }
        val schedulerToken = response.tokens.scheduler?.takeIf { it.isNotBlank() }
        // Prefer surgeon when dual (matches iOS / native OTP primary_role).
        val activeRole = when {
            surgeonToken != null &&
                (parsedRoles.isEmpty() || SessionRole.SURGEON in parsedRoles) -> SessionRole.SURGEON
            else -> SessionRole.fromStoredValue(response.role).let { role ->
                if (parsedRoles.isEmpty() || role in parsedRoles) role else parsedRoles.first()
            }
        }
        val activeToken = when (activeRole) {
            SessionRole.SURGEON -> surgeonToken ?: response.token
            SessionRole.SCHEDULER -> schedulerToken ?: response.token
        }
        saveDualSession(
            activeToken = activeToken,
            activeRole = activeRole,
            availableRoles = parsedRoles.ifEmpty { listOf(activeRole) },
            surgeonToken = surgeonToken,
            schedulerToken = schedulerToken,
        )
    }

    fun saveSession(
        token: String,
        deviceToken: String = token,
        role: SessionRole = SessionRole.SURGEON,
    ) {
        saveDualSession(
            activeToken = token,
            activeRole = role,
            availableRoles = listOf(role),
            surgeonToken = if (role == SessionRole.SURGEON) token else null,
            schedulerToken = if (role == SessionRole.SCHEDULER) token else null,
            deviceToken = deviceToken,
        )
    }

    fun saveDualSession(
        activeToken: String,
        activeRole: SessionRole,
        availableRoles: List<SessionRole>,
        surgeonToken: String?,
        schedulerToken: String?,
        deviceToken: String = activeToken,
    ) {
        preferences.edit()
            .putString(KEY_TOKEN, activeToken)
            .putString(KEY_DEVICE_TOKEN, deviceToken)
            .putString(KEY_ROLE, activeRole.storedValue)
            .putString(
                KEY_AVAILABLE_ROLES,
                availableRoles.joinToString(",") { it.storedValue },
            )
            .putString(KEY_SURGEON_TOKEN, surgeonToken)
            .putString(KEY_SCHEDULER_TOKEN, schedulerToken)
            .apply()
        this.token = activeToken
        this.deviceToken = deviceToken
        this.role = activeRole
        this.availableRoles = availableRoles.ifEmpty { listOf(activeRole) }
        preferOtp = false
    }

    /** Load prefs into active session after biometric success. */
    fun unlockStoredSession(): Boolean {
        val stored = preferences.getString(KEY_TOKEN, null)
        if (stored.isNullOrBlank()) return false
        val storedDevice = preferences.getString(KEY_DEVICE_TOKEN, null)?.takeIf { it.isNotBlank() }
            ?: stored
        token = stored
        deviceToken = storedDevice
        role = SessionRole.fromStoredValue(preferences.getString(KEY_ROLE, null))
        availableRoles = readAvailableRoles()
        preferOtp = false
        return true
    }

    fun clear() {
        preferences.edit().clear().apply()
        token = null
        deviceToken = null
        role = SessionRole.SURGEON
        availableRoles = listOf(SessionRole.SURGEON)
        preferOtp = false
    }

    private fun readAvailableRoles(): List<SessionRole> {
        val raw = preferences.getString(KEY_AVAILABLE_ROLES, null).orEmpty()
        val parsed = raw.split(",")
            .mapNotNull { part ->
                SessionRole.entries.firstOrNull { it.storedValue == part.trim() }
            }
        return parsed.ifEmpty {
            listOf(SessionRole.fromStoredValue(preferences.getString(KEY_ROLE, null)))
        }
    }

    private companion object {
        const val PREFERENCES_NAME = "cal_session_encrypted"
        const val LEGACY_PREFERENCES_NAME = "cal_session"
        const val KEY_TOKEN = "token"
        const val KEY_DEVICE_TOKEN = "device_token"
        const val KEY_ROLE = "role"
        const val KEY_AVAILABLE_ROLES = "available_roles"
        const val KEY_SURGEON_TOKEN = "surgeon_token"
        const val KEY_SCHEDULER_TOKEN = "scheduler_token"

        fun createSecurePreferences(context: Context): SharedPreferences {
            val masterKey = MasterKey.Builder(context)
                .setKeyScheme(MasterKey.KeyScheme.AES256_GCM)
                .build()
            val secure = EncryptedSharedPreferences.create(
                context,
                PREFERENCES_NAME,
                masterKey,
                EncryptedSharedPreferences.PrefKeyEncryptionScheme.AES256_SIV,
                EncryptedSharedPreferences.PrefValueEncryptionScheme.AES256_GCM,
            )
            migrateFromLegacyIfNeeded(context, secure)
            return secure
        }

        fun migrateFromLegacyIfNeeded(context: Context, secure: SharedPreferences) {
            if (secure.contains(KEY_TOKEN)) return
            val legacy = context.getSharedPreferences(LEGACY_PREFERENCES_NAME, Context.MODE_PRIVATE)
            val token = legacy.getString(KEY_TOKEN, null) ?: return
            if (token.isBlank()) return
            secure.edit()
                .putString(KEY_TOKEN, token)
                .putString(KEY_DEVICE_TOKEN, legacy.getString(KEY_DEVICE_TOKEN, token))
                .putString(KEY_ROLE, legacy.getString(KEY_ROLE, SessionRole.SURGEON.storedValue))
                .apply()
            legacy.edit().clear().apply()
        }
    }
}
