package com.midfloridasurgical.calcompose.surgeon.patients

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.rounded.ChevronLeft
import androidx.compose.material.icons.rounded.ChevronRight
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.midfloridasurgical.calcompose.data.CalApiClient
import com.midfloridasurgical.calcompose.data.models.NativePatientAppointment
import com.midfloridasurgical.calcompose.data.models.NativeSurgeon
import com.midfloridasurgical.calcompose.ui.theme.ClinicalPalette
import com.midfloridasurgical.calcompose.ui.theme.ClinicalTypography
import com.midfloridasurgical.calcompose.ui.theme.LiquidGlassCard
import com.midfloridasurgical.calcompose.ui.theme.clinicalPageBackground
import com.midfloridasurgical.calcompose.util.onFailureUnlessCancelled
import java.time.LocalDate
import java.time.format.DateTimeFormatter
import java.util.Locale
import kotlinx.coroutines.delay

@Composable
fun PatientScheduleScreen(
    apiClient: CalApiClient,
    token: String,
    deviceToken: String,
    currentSurgeon: NativeSurgeon?,
) {
    var anchorDate by remember { mutableStateOf(LocalDate.now()) }
    var appointments by remember { mutableStateOf<List<NativePatientAppointment>>(emptyList()) }
    var warning by remember { mutableStateOf<String?>(null) }
    var isLoading by remember { mutableStateOf(true) }

    LaunchedEffect(anchorDate, token, deviceToken) {
        delay(120) // debounce week stepper
        while (true) {
            isLoading = appointments.isEmpty()
            warning = null
            val start = anchorDate
            val end = anchorDate.plusDays(6)
            try {
                runCatching {
                    apiClient.fetchPatientSchedule(token, deviceToken, start, end)
                }.onSuccess { response ->
                    appointments = filterMyAppointments(response.appointments, currentSurgeon)
                    warning = response.warning
                }.onFailureUnlessCancelled {
                    if (appointments.isEmpty()) {
                        warning = it.message ?: "Could not load patient schedule."
                    }
                }
            } finally {
                isLoading = false
            }
            delay(5 * 60 * 1000L)
        }
    }

    val dayEntries = remember(appointments) {
        appointments
            .groupBy { it.date }
            .toSortedMap()
            .map { (date, rows) ->
                date to rows.sortedWith(compareBy({ it.start }, { it.patientName }))
            }
    }

    LazyColumn(
        modifier = Modifier
            .fillMaxSize()
            .clinicalPageBackground()
            .padding(horizontal = 16.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
        contentPadding = PaddingValues(vertical = 16.dp),
    ) {
        item(key = "header") {
            LiquidGlassCard(tint = ClinicalPalette.CardStrong, cornerRadius = 16.dp) {
                Row(
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(horizontal = 4.dp, vertical = 6.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    IconButton(onClick = { anchorDate = anchorDate.minusDays(7) }) {
                        Icon(
                            Icons.Rounded.ChevronLeft,
                            contentDescription = "Previous week",
                            tint = ClinicalPalette.Ink,
                        )
                    }
                    Column(
                        modifier = Modifier.weight(1f),
                        horizontalAlignment = Alignment.CenterHorizontally,
                    ) {
                        Text(
                            "Patient schedule",
                            style = ClinicalTypography.rowTitleStrong,
                            color = ClinicalPalette.Ink,
                        )
                        Text(
                            "${anchorDate.format(monthDay)} – ${anchorDate.plusDays(6).format(monthDay)}",
                            style = ClinicalTypography.caption,
                            color = ClinicalPalette.Muted,
                        )
                    }
                    IconButton(onClick = { anchorDate = anchorDate.plusDays(7) }) {
                        Icon(
                            Icons.Rounded.ChevronRight,
                            contentDescription = "Next week",
                            tint = ClinicalPalette.Ink,
                        )
                    }
                }
            }
        }

        warning?.let { message ->
            item(key = "warning") {
                LiquidGlassCard(tint = ClinicalPalette.Amber, cornerRadius = 14.dp) {
                    Text(
                        message,
                        style = ClinicalTypography.caption,
                        color = ClinicalPalette.Muted,
                        modifier = Modifier
                            .fillMaxWidth()
                            .padding(12.dp),
                    )
                }
            }
        }

        when {
            isLoading -> {
                item(key = "loading") {
                    CircularProgressIndicator(
                        modifier = Modifier
                            .fillMaxWidth()
                            .padding(24.dp),
                        color = ClinicalPalette.Teal,
                    )
                }
            }
            dayEntries.isEmpty() -> {
                item(key = "empty") {
                    Text(
                        "No patient appointments in this range.",
                        style = ClinicalTypography.caption,
                        color = ClinicalPalette.Muted,
                    )
                }
            }
            else -> {
                items(
                    items = dayEntries,
                    key = { it.first },
                ) { (date, rows) ->
                    LiquidGlassCard(tint = ClinicalPalette.Card, cornerRadius = 16.dp) {
                        Column(
                            modifier = Modifier.padding(14.dp),
                            verticalArrangement = Arrangement.spacedBy(8.dp),
                        ) {
                            Text(
                                date,
                                style = ClinicalTypography.rowTitleStrong,
                                color = ClinicalPalette.Ink,
                            )
                            rows.forEach { appt ->
                                Column(
                                    modifier = Modifier
                                        .fillMaxWidth()
                                        .background(
                                            ClinicalPalette.TealSoft.copy(alpha = 0.4f),
                                            RoundedCornerShape(12.dp),
                                        )
                                        .padding(10.dp),
                                ) {
                                    Text(
                                        "${appt.start}–${appt.end} · ${appt.patientName}",
                                        style = ClinicalTypography.rowTitle,
                                        color = ClinicalPalette.Ink,
                                    )
                                    val detail = listOfNotNull(
                                        appt.appointmentType.takeIf { it.isNotBlank() },
                                        appt.serviceSite.takeIf { it.isNotBlank() },
                                        appt.room.takeIf { it.isNotBlank() },
                                        appt.status.takeIf { it.isNotBlank() },
                                    ).joinToString(" · ")
                                    if (detail.isNotBlank()) {
                                        Text(
                                            detail,
                                            style = ClinicalTypography.caption,
                                            color = ClinicalPalette.Muted,
                                        )
                                    }
                                    if (appt.reason.isNotBlank()) {
                                        Text(
                                            appt.reason,
                                            style = ClinicalTypography.caption,
                                            color = ClinicalPalette.Muted,
                                        )
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
    }
}

private val monthDay: DateTimeFormatter = DateTimeFormatter.ofPattern("MMM d", Locale.US)

private fun filterMyAppointments(
    appointments: List<NativePatientAppointment>,
    currentSurgeon: NativeSurgeon?,
): List<NativePatientAppointment> {
    val myInitials = currentSurgeon?.initials?.trim()?.uppercase().orEmpty()
    val myName = currentSurgeon?.name?.trim()?.lowercase().orEmpty()
    if (myInitials.isEmpty() && myName.isEmpty()) return appointments
    return appointments.filter { appointment ->
        val initials = appointment.surgeonInitials.uppercase()
        if (myInitials.isNotEmpty() && initials == myInitials) return@filter true
        val name = appointment.surgeonName.lowercase()
        myName.isNotEmpty() && (name == myName || name.contains(myName) || myName.contains(name))
    }
}
