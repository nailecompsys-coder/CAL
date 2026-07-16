package com.midfloridasurgical.calcompose.auth

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.midfloridasurgical.calcompose.data.CalApiClient
import com.midfloridasurgical.calcompose.data.CalSessionStore
import com.midfloridasurgical.calcompose.data.models.SessionRole
import com.midfloridasurgical.calcompose.ui.theme.ClinicalPalette
import kotlinx.coroutines.launch

@Composable
fun AuthScreen(
    apiClient: CalApiClient,
    sessionStore: CalSessionStore,
) {
    var identifier by remember { mutableStateOf("") }
    var code by remember { mutableStateOf("") }
    var selectedRole by remember { mutableStateOf(SessionRole.SURGEON) }
    var statusMessage by remember { mutableStateOf<String?>(null) }
    var busy by remember { mutableStateOf(false) }
    val scope = rememberCoroutineScope()
    val normalizedIdentifier = identifier.trim()
    val schedulerSelected = selectedRole == SessionRole.SCHEDULER

    Column(
        modifier = Modifier
            .fillMaxSize()
            .background(
                Brush.linearGradient(
                    listOf(ClinicalPalette.PageTop, ClinicalPalette.PageBottom),
                ),
            )
            .padding(horizontal = 20.dp, vertical = 28.dp),
        verticalArrangement = Arrangement.Center,
    ) {
        Text("CAL", fontSize = 22.sp, fontWeight = FontWeight.Bold)
        Text(
            "Mid Florida Surgical",
            color = ClinicalPalette.Muted,
            fontSize = 14.sp,
        )
        Spacer(Modifier.height(8.dp))
        Text("Sign in", fontSize = 32.sp, fontWeight = FontWeight.Bold)
        Spacer(Modifier.height(28.dp))

        Card(
            modifier = Modifier.fillMaxWidth(),
            shape = RoundedCornerShape(20.dp),
            colors = CardDefaults.cardColors(containerColor = ClinicalPalette.Card),
        ) {
            Column(
                modifier = Modifier.padding(18.dp),
                verticalArrangement = Arrangement.spacedBy(12.dp),
            ) {
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.spacedBy(8.dp),
                ) {
                    RoleButton(
                        label = "Surgeon",
                        selected = selectedRole == SessionRole.SURGEON,
                        onClick = { selectedRole = SessionRole.SURGEON },
                        modifier = Modifier.weight(1f),
                    )
                    RoleButton(
                        label = "Scheduler",
                        selected = schedulerSelected,
                        onClick = { selectedRole = SessionRole.SCHEDULER },
                        modifier = Modifier.weight(1f),
                    )
                }

                Text(
                    if (schedulerSelected) {
                        "Scheduler sign-in will be enabled with the Android scheduler workflow."
                    } else {
                        "Surgeon email or iPhone, tap Send, then enter the 6-digit code."
                    },
                    color = ClinicalPalette.Muted,
                    fontSize = 12.sp,
                    fontWeight = FontWeight.SemiBold,
                )

                OutlinedTextField(
                    value = identifier,
                    onValueChange = { identifier = it },
                    modifier = Modifier.fillMaxWidth(),
                    label = { Text("Email or iPhone") },
                    singleLine = true,
                    keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Email),
                )

                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.spacedBy(10.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    OutlinedButton(
                        onClick = {
                            scope.launch {
                                busy = true
                                statusMessage = runCatching {
                                    apiClient.requestOtp(normalizedIdentifier).message
                                        ?: "Check your email or iPhone for the CAL code."
                                }.getOrElse { it.message ?: "Could not send a CAL code." }
                                busy = false
                            }
                        },
                        enabled = !busy && normalizedIdentifier.isNotEmpty() && !schedulerSelected,
                    ) {
                        Text("Send")
                    }

                    OutlinedTextField(
                        value = code,
                        onValueChange = {
                            code = it.filter(Char::isDigit).take(6)
                        },
                        modifier = Modifier.weight(1f),
                        label = { Text("6-digit code") },
                        singleLine = true,
                        keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
                    )
                }

                Button(
                    onClick = {
                        scope.launch {
                            busy = true
                            statusMessage = runCatching {
                                val response = apiClient.verifyOtp(
                                    normalizedIdentifier,
                                    code,
                                )
                                sessionStore.saveSession(
                                    token = response.token,
                                    deviceToken = response.token,
                                    role = SessionRole.SURGEON,
                                )
                                null
                            }.getOrElse { it.message ?: "Sign in failed." }
                            busy = false
                        }
                    },
                    modifier = Modifier.fillMaxWidth(),
                    enabled = !busy &&
                        !schedulerSelected &&
                        normalizedIdentifier.isNotEmpty() &&
                        code.length == 6,
                ) {
                    Text(if (busy) "Please wait…" else "Sign in")
                }

                statusMessage?.let {
                    Text(it, color = ClinicalPalette.Muted, fontSize = 12.sp)
                }
            }
        }
    }
}

@Composable
private fun RoleButton(
    label: String,
    selected: Boolean,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
) {
    if (selected) {
        Button(onClick = onClick, modifier = modifier) {
            Text(label)
        }
    } else {
        OutlinedButton(onClick = onClick, modifier = modifier) {
            Text(label)
        }
    }
}
