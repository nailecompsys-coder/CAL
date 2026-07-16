package com.midfloridasurgical.calcompose.surgeon.timeoff

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.midfloridasurgical.calcompose.data.SurgeonHomeStore
import com.midfloridasurgical.calcompose.ui.theme.ClinicalPalette
import java.time.LocalDate
import kotlinx.coroutines.launch

@Composable
fun TimeOffScreen(store: SurgeonHomeStore) {
    var showForm by remember { mutableStateOf(false) }
    var statusMessage by remember { mutableStateOf<String?>(null) }
    val scope = rememberCoroutineScope()

    LaunchedEffect(Unit) {
        if (store.days.isEmpty()) {
            store.refresh()
        }
    }

    Column(
        modifier = Modifier
            .fillMaxSize()
            .background(
                Brush.linearGradient(
                    listOf(ClinicalPalette.PageTop, ClinicalPalette.PageBottom),
                ),
            )
            .verticalScroll(rememberScrollState())
            .padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        Button(
            onClick = { showForm = true },
            modifier = Modifier.fillMaxWidth(),
        ) {
            Text("Request Time Off")
        }

        statusMessage?.let {
            Text(it, color = ClinicalPalette.Muted, fontSize = 13.sp)
        }
        store.warningMessage?.let {
            Text(it, color = ClinicalPalette.Muted, fontSize = 13.sp)
        }

        Text(
            "MY REQUESTS",
            color = ClinicalPalette.Muted,
            fontSize = 12.sp,
            fontWeight = FontWeight.Bold,
        )

        when {
            store.isLoading && store.requests.isEmpty() -> {
                CircularProgressIndicator(modifier = Modifier.align(Alignment.CenterHorizontally))
            }
            store.requests.isEmpty() -> {
                Text("No time-off requests loaded.", color = ClinicalPalette.Muted)
            }
            else -> {
                store.requests.forEach { request ->
                    Card(
                        modifier = Modifier.fillMaxWidth(),
                        shape = RoundedCornerShape(16.dp),
                        colors = CardDefaults.cardColors(containerColor = ClinicalPalette.Card),
                    ) {
                        Column(
                            modifier = Modifier.padding(14.dp),
                            verticalArrangement = Arrangement.spacedBy(4.dp),
                        ) {
                            Text(
                                "${request.startDate} → ${request.endDate}",
                                fontWeight = FontWeight.Bold,
                            )
                            Text(
                                request.reason.ifBlank { "No reason provided" },
                                color = ClinicalPalette.Muted,
                                fontSize = 13.sp,
                            )
                            Text(
                                request.status.ifBlank { "pending" }.uppercase(),
                                color = ClinicalPalette.Teal,
                                fontSize = 12.sp,
                                fontWeight = FontWeight.Bold,
                            )
                        }
                    }
                }
            }
        }
        Spacer(modifier = Modifier.height(12.dp))
    }

    if (showForm) {
        TimeOffRequestDialog(
            busy = store.isLoading,
            onDismiss = { showForm = false },
            onSubmit = { start, end, reason ->
                scope.launch {
                    runCatching {
                        val warnings = store.submitTimeOff(start, end, reason)
                        statusMessage = if (warnings.isEmpty()) {
                            "Time-off request submitted."
                        } else {
                            warnings.joinToString(" ")
                        }
                        showForm = false
                    }.onFailure {
                        statusMessage = it.message ?: "Could not submit time off."
                    }
                }
            },
        )
    }
}

@Composable
private fun TimeOffRequestDialog(
    busy: Boolean,
    onDismiss: () -> Unit,
    onSubmit: (LocalDate, LocalDate, String) -> Unit,
) {
    val today = LocalDate.now()
    var startText by remember { mutableStateOf(today.toString()) }
    var endText by remember { mutableStateOf(today.toString()) }
    var reason by remember { mutableStateOf("") }
    var formError by remember { mutableStateOf<String?>(null) }

    AlertDialog(
        onDismissRequest = { if (!busy) onDismiss() },
        title = { Text("Request time off") },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
                OutlinedTextField(
                    value = startText,
                    onValueChange = { startText = it },
                    label = { Text("Start (yyyy-MM-dd)") },
                    singleLine = true,
                    modifier = Modifier.fillMaxWidth(),
                )
                OutlinedTextField(
                    value = endText,
                    onValueChange = { endText = it },
                    label = { Text("End (yyyy-MM-dd)") },
                    singleLine = true,
                    modifier = Modifier.fillMaxWidth(),
                )
                OutlinedTextField(
                    value = reason,
                    onValueChange = { reason = it },
                    label = { Text("Reason") },
                    modifier = Modifier.fillMaxWidth(),
                )
                formError?.let {
                    Text(it, color = ClinicalPalette.Muted, fontSize = 12.sp)
                }
            }
        },
        confirmButton = {
            TextButton(
                enabled = !busy,
                onClick = {
                    val start = runCatching { LocalDate.parse(startText.trim()) }.getOrNull()
                    val end = runCatching { LocalDate.parse(endText.trim()) }.getOrNull()
                    when {
                        start == null || end == null -> formError = "Use yyyy-MM-dd dates."
                        end.isBefore(start) -> formError = "End date must be on or after start."
                        reason.isBlank() -> formError = "Enter a reason."
                        else -> onSubmit(start, end, reason.trim())
                    }
                },
            ) {
                Text(if (busy) "Submitting…" else "Submit")
            }
        },
        dismissButton = {
            TextButton(onClick = onDismiss, enabled = !busy) {
                Text("Cancel")
            }
        },
    )
}
