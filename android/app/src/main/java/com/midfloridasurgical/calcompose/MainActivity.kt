package com.midfloridasurgical.calcompose

import android.os.Bundle
import androidx.activity.compose.setContent
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.compose.ui.Modifier
import androidx.fragment.app.FragmentActivity
import com.midfloridasurgical.calcompose.auth.AuthScreen
import com.midfloridasurgical.calcompose.auth.BiometricUnlockScreen
import com.midfloridasurgical.calcompose.data.CalApiClient
import com.midfloridasurgical.calcompose.data.CalSessionStore
import com.midfloridasurgical.calcompose.surgeon.SurgeonShell
import com.midfloridasurgical.calcompose.ui.theme.CALTheme

class MainActivity : FragmentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent {
            CALTheme {
                Box(modifier = Modifier.fillMaxSize()) {
                    CALRoot()
                }
            }
        }
    }

    @Composable
    private fun CALRoot() {
        val sessionStore = remember {
            CalSessionStore(applicationContext)
        }
        val apiClient = remember { CalApiClient() }
        val token = sessionStore.token
        val deviceToken = sessionStore.deviceToken

        when {
            token != null && deviceToken != null -> {
                SurgeonShell(
                    apiClient = apiClient,
                    sessionStore = sessionStore,
                    token = token,
                    deviceToken = deviceToken,
                )
            }
            sessionStore.hasStoredSession && !sessionStore.preferOtp -> {
                BiometricUnlockScreen(
                    sessionStore = sessionStore,
                    onUseOtp = { sessionStore.preferOtp = true },
                )
            }
            else -> {
                AuthScreen(
                    apiClient = apiClient,
                    sessionStore = sessionStore,
                )
            }
        }
    }
}
