package com.midfloridasurgical.calcompose.auth

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.BasicTextField
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.SolidColor
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import com.midfloridasurgical.calcompose.data.CalApiClient
import com.midfloridasurgical.calcompose.data.CalSessionStore
import com.midfloridasurgical.calcompose.ui.theme.ClinicalAuthBackground
import com.midfloridasurgical.calcompose.ui.theme.ClinicalPalette
import com.midfloridasurgical.calcompose.ui.theme.ClinicalPrimaryButton
import com.midfloridasurgical.calcompose.ui.theme.ClinicalSendChip
import com.midfloridasurgical.calcompose.ui.theme.ClinicalTypography
import com.midfloridasurgical.calcompose.ui.theme.authFieldChrome
import com.midfloridasurgical.calcompose.ui.theme.authGlassSurface
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.launch
import java.time.LocalDate
import java.time.format.DateTimeFormatter
import java.util.Locale

@Composable
fun AuthScreen(
    apiClient: CalApiClient,
    sessionStore: CalSessionStore,
) {
    var identifier by remember { mutableStateOf("") }
    var code by remember { mutableStateOf("") }
    var statusMessage by remember { mutableStateOf<String?>(null) }
    var busy by remember { mutableStateOf(false) }
    val scope = rememberCoroutineScope()
    val normalizedIdentifier = identifier.trim()
    val normalizedCode = code.trim()
    val todayText = remember {
        LocalDate.now().format(
            DateTimeFormatter.ofPattern("EEE MM/dd/yy", Locale.US),
        )
    }

    fun sendCode() {
        scope.launch {
            busy = true
            try {
                statusMessage = runCatching {
                    val response = apiClient.requestOtp(normalizedIdentifier)
                    if (response.ok == false || response.sent == false) {
                        response.message?.takeIf { it.isNotBlank() }
                            ?: "Could not send a code. Try again or contact the office."
                    } else {
                        response.devCode?.takeIf { it.isNotBlank() }?.let { "Local access code: $it" }
                            ?: response.message
                            ?: "Check your email or iPhone for the CAL access code."
                    }
                }.getOrElse {
                    if (it is CancellationException) throw it
                    it.message ?: "Could not send a code. Try again or contact the office."
                }
            } finally {
                busy = false
            }
        }
    }

    fun signIn() {
        scope.launch {
            busy = true
            try {
                statusMessage = runCatching {
                    val response = apiClient.verifyOtp(
                        normalizedIdentifier,
                        normalizedCode,
                    )
                    sessionStore.saveFromVerify(response)
                    null
                }.getOrElse {
                    if (it is CancellationException) throw it
                    it.message ?: "Sign in failed."
                }
            } finally {
                busy = false
            }
        }
    }

    Box(modifier = Modifier.fillMaxSize()) {
        ClinicalAuthBackground()

        Column(
            modifier = Modifier
                .fillMaxSize()
                .verticalScroll(rememberScrollState())
                .padding(horizontal = 18.dp)
                .padding(top = 14.dp, bottom = 30.dp),
            verticalArrangement = Arrangement.Top,
        ) {
            Text("CAL", style = ClinicalTypography.largeTitle, color = ClinicalPalette.Ink)
            Text(
                "Mid Florida Surgical",
                style = ClinicalTypography.headline,
                color = ClinicalPalette.Muted,
                maxLines = 1,
            )
            Spacer(modifier = Modifier.height(8.dp))
            Text("Sign in", style = ClinicalTypography.title, color = ClinicalPalette.Ink)
            Text(
                todayText,
                style = ClinicalTypography.bodyMedium,
                color = ClinicalPalette.Muted,
            )

            Spacer(modifier = Modifier.height(48.dp))

            Column(
                modifier = Modifier
                    .fillMaxWidth()
                    .authGlassSurface(cornerRadius = 16.dp)
                    .padding(18.dp),
                verticalArrangement = Arrangement.spacedBy(12.dp),
            ) {
                Text(
                    "Email or iPhone, tap Send, then enter the 6-digit code.",
                    style = ClinicalTypography.caption,
                    color = ClinicalPalette.Muted,
                    maxLines = 2,
                )

                AuthCapsuleField(
                    value = identifier,
                    onValueChange = { identifier = it },
                    placeholder = "Email or iPhone",
                    keyboardType = KeyboardType.Email,
                    imeAction = ImeAction.Send,
                    onIme = { if (normalizedIdentifier.isNotEmpty() && !busy) sendCode() },
                )

                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.spacedBy(10.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    ClinicalSendChip(
                        onClick = { sendCode() },
                        enabled = !busy && normalizedIdentifier.isNotEmpty(),
                    )
                    AuthCapsuleField(
                        value = code,
                        onValueChange = { code = it.filter(Char::isDigit).take(6) },
                        placeholder = "6-digit code",
                        keyboardType = KeyboardType.Number,
                        imeAction = ImeAction.Go,
                        onIme = {
                            if (
                                !busy &&
                                normalizedIdentifier.isNotEmpty() &&
                                normalizedCode.isNotEmpty()
                            ) {
                                signIn()
                            }
                        },
                        modifier = Modifier.weight(1f),
                    )
                }

                ClinicalPrimaryButton(
                    text = "Sign in",
                    onClick = { signIn() },
                    enabled = normalizedIdentifier.isNotEmpty() && normalizedCode.isNotEmpty(),
                    busy = busy,
                )

                statusMessage?.let {
                    Text(it, style = ClinicalTypography.caption, color = ClinicalPalette.Muted)
                }
            }
        }
    }
}

@Composable
private fun AuthCapsuleField(
    value: String,
    onValueChange: (String) -> Unit,
    placeholder: String,
    keyboardType: KeyboardType,
    imeAction: ImeAction,
    onIme: () -> Unit,
    modifier: Modifier = Modifier,
) {
    BasicTextField(
        value = value,
        onValueChange = onValueChange,
        singleLine = true,
        textStyle = ClinicalTypography.rowTitle.copy(color = ClinicalPalette.Ink),
        cursorBrush = SolidColor(ClinicalPalette.Teal),
        keyboardOptions = KeyboardOptions(
            keyboardType = keyboardType,
            imeAction = imeAction,
        ),
        keyboardActions = KeyboardActions(
            onSend = { onIme() },
            onGo = { onIme() },
            onDone = { onIme() },
        ),
        modifier = modifier
            .fillMaxWidth()
            .authFieldChrome()
            .padding(horizontal = 14.dp, vertical = 14.dp),
        decorationBox = { inner ->
            Box {
                if (value.isEmpty()) {
                    Text(
                        placeholder,
                        style = ClinicalTypography.rowTitle,
                        color = ClinicalPalette.Muted.copy(alpha = 0.65f),
                    )
                }
                inner()
            }
        },
    )
}
