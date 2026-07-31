package com.midfloridasurgical.calcompose.auth

import android.content.Context
import androidx.biometric.BiometricManager
import androidx.biometric.BiometricPrompt
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import androidx.core.content.ContextCompat
import androidx.fragment.app.FragmentActivity
import com.midfloridasurgical.calcompose.BuildConfig
import com.midfloridasurgical.calcompose.data.CalSessionStore
import com.midfloridasurgical.calcompose.ui.theme.ClinicalPalette
import com.midfloridasurgical.calcompose.ui.theme.ClinicalTypography
import com.midfloridasurgical.calcompose.ui.theme.LiquidGlassCard

/**
 * Mirrors iOS `NativeBiometricService` + unlock-before-session-token.
 * When biometrics are unavailable: DEBUG auto-unlocks stored session; release falls to OTP.
 */
@Composable
fun BiometricUnlockScreen(
    sessionStore: CalSessionStore,
    onUseOtp: () -> Unit,
) {
    val context = LocalContext.current
    var status by remember { mutableStateOf("Unlock CAL with biometrics") }
    var prompted by remember { mutableStateOf(false) }

    fun unlockNow() {
        if (sessionStore.unlockStoredSession()) {
            status = "Unlocked"
        } else {
            status = "No stored session"
            onUseOtp()
        }
    }

    fun promptBiometric() {
        val activity = context.findFragmentActivity()
        if (activity == null) {
            if (BuildConfig.DEBUG) unlockNow() else onUseOtp()
            return
        }
        val manager = BiometricManager.from(context)
        val can = manager.canAuthenticate(BiometricManager.Authenticators.BIOMETRIC_STRONG)
        if (can != BiometricManager.BIOMETRIC_SUCCESS) {
            if (BuildConfig.DEBUG) {
                status = "Biometrics unavailable — unlocking stored session (debug)"
                unlockNow()
            } else {
                status = "Biometrics unavailable — use OTP"
            }
            return
        }
        val executor = ContextCompat.getMainExecutor(context)
        val prompt = BiometricPrompt(
            activity,
            executor,
            object : BiometricPrompt.AuthenticationCallback() {
                override fun onAuthenticationSucceeded(result: BiometricPrompt.AuthenticationResult) {
                    unlockNow()
                }

                override fun onAuthenticationError(errorCode: Int, errString: CharSequence) {
                    if (errorCode == BiometricPrompt.ERROR_NEGATIVE_BUTTON ||
                        errorCode == BiometricPrompt.ERROR_USER_CANCELED ||
                        errorCode == BiometricPrompt.ERROR_CANCELED
                    ) {
                        status = "Use OTP to sign in"
                    } else {
                        status = errString.toString()
                    }
                }

                override fun onAuthenticationFailed() {
                    status = "Biometric not recognized — try again or use OTP"
                }
            },
        )
        prompt.authenticate(
            BiometricPrompt.PromptInfo.Builder()
                .setTitle("Unlock CAL")
                .setSubtitle("Confirm it's you to open your schedule")
                .setNegativeButtonText("Use OTP")
                .build(),
        )
    }

    LaunchedEffect(Unit) {
        if (!prompted) {
            prompted = true
            promptBiometric()
        }
    }

    Column(
        modifier = Modifier
            .fillMaxSize()
            .background(
                Brush.linearGradient(
                    listOf(ClinicalPalette.PageTop, ClinicalPalette.PageMiddle, ClinicalPalette.PageBottom),
                ),
            )
            .padding(24.dp),
        verticalArrangement = Arrangement.Center,
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        LiquidGlassCard(tint = ClinicalPalette.TealSoft, cornerRadius = 18.dp) {
            Column(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(18.dp),
                verticalArrangement = Arrangement.spacedBy(12.dp),
                horizontalAlignment = Alignment.CenterHorizontally,
            ) {
                Text("CAL", style = ClinicalTypography.largeTitle, color = ClinicalPalette.Ink)
                Text(status, style = ClinicalTypography.caption, color = ClinicalPalette.Muted)
                Spacer(modifier = Modifier.height(4.dp))
                Button(
                    onClick = { promptBiometric() },
                    modifier = Modifier.fillMaxWidth(),
                    colors = ButtonDefaults.buttonColors(
                        containerColor = ClinicalPalette.Teal,
                        contentColor = ClinicalPalette.OnTeal,
                    ),
                    shape = RoundedCornerShape(12.dp),
                ) {
                    Text("Unlock", style = ClinicalTypography.headline)
                }
                OutlinedButton(
                    onClick = onUseOtp,
                    modifier = Modifier.fillMaxWidth(),
                    shape = RoundedCornerShape(12.dp),
                ) {
                    Text("Use OTP", color = ClinicalPalette.Teal, style = ClinicalTypography.rowTitle)
                }
            }
        }
    }
}

private fun Context.findFragmentActivity(): FragmentActivity? {
    var current: Context? = this
    while (current is android.content.ContextWrapper) {
        if (current is FragmentActivity) return current
        current = current.baseContext
    }
    return null
}
