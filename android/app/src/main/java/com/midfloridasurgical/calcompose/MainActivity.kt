package com.midfloridasurgical.calcompose

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.material3.Surface
import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import com.midfloridasurgical.calcompose.auth.AuthScreen
import com.midfloridasurgical.calcompose.data.CalApiClient
import com.midfloridasurgical.calcompose.data.CalSessionStore
import com.midfloridasurgical.calcompose.surgeon.SurgeonShell
import com.midfloridasurgical.calcompose.ui.theme.CALTheme

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent {
            CALTheme {
                Surface {
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

        if (token == null || deviceToken == null) {
            AuthScreen(
                apiClient = apiClient,
                sessionStore = sessionStore,
            )
        } else {
            SurgeonShell(
                apiClient = apiClient,
                sessionStore = sessionStore,
                token = token,
                deviceToken = deviceToken,
            )
        }
    }
}
