package com.midfloridasurgical.calcompose.data

import android.content.Context
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import com.midfloridasurgical.calcompose.data.models.SessionRole

class CalSessionStore(context: Context) {
    private val preferences =
        context.getSharedPreferences(PREFERENCES_NAME, Context.MODE_PRIVATE)

    var token by mutableStateOf(preferences.getString(KEY_TOKEN, null))
        private set

    var deviceToken by mutableStateOf(preferences.getString(KEY_DEVICE_TOKEN, null))
        private set

    var role by mutableStateOf(
        SessionRole.fromStoredValue(preferences.getString(KEY_ROLE, null)),
    )
        private set

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
    }

    fun clear() {
        preferences.edit().clear().apply()
        token = null
        deviceToken = null
        role = SessionRole.SURGEON
    }

    private companion object {
        const val PREFERENCES_NAME = "cal_session"
        const val KEY_TOKEN = "token"
        const val KEY_DEVICE_TOKEN = "device_token"
        const val KEY_ROLE = "role"
    }
}
