package com.midfloridasurgical.calcompose.surgeon.patients

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.rounded.ChevronLeft
import androidx.compose.material.icons.rounded.ChevronRight
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
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
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.midfloridasurgical.calcompose.data.CalApiClient
import com.midfloridasurgical.calcompose.data.models.NativePatientAppointment
import com.midfloridasurgical.calcompose.data.models.NativeSurgeon
import com.midfloridasurgical.calcompose.ui.theme.ClinicalPalette
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
        while (true) {
            isLoading = appointments.isEmpty()
            warning = null
            val start = anchorDate
            val end = anchorDate.plusDays(6)
            runCatching {
                apiClient.fetchPatientSchedule(token, deviceToken, start, end)
            }.onSuccess { response ->
                appointments = filterMyAppointments(response.appointments, currentSurgeon)
                warning = response.warning
            }.onFailure {
                if (appointments.isEmpty()) {
                    warning = it.message ?: "Could not load patient schedule."
                }
            }
            isLoading = false
            delay(5 * 60 * 1000L)
        }
    }

    val byDay = appointments
        .groupBy { it.date }
        .toSortedMap()
        .mapValues { (_, rows) ->
            rows.sortedWith(compareBy({ it.start }, { it.patientName }))
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
        Card(
            modifier = Modifier.fillMaxWidth(),
            shape = RoundedCornerShape(16.dp),
            colors = CardDefaults.cardColors(containerColor = ClinicalPalette.Card),
        ) {
            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(horizontal = 4.dp, vertical = 6.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                IconButton(onClick = { anchorDate = anchorDate.minusDays(7) }) {
                    Icon(Icons.Rounded.ChevronLeft, contentDescription = "Previous week")
                }
                Column(
                    modifier = Modifier.weight(1f),
                    horizontalAlignment = Alignment.CenterHorizontally,
                ) {
                    Text("Patient schedule", fontWeight = FontWeight.Bold)
                    Text(
                        "${anchorDate.format(monthDay)} – ${anchorDate.plusDays(6).format(monthDay)}",
                        color = ClinicalPalette.Muted,
                        fontSize = 12.sp,
                    )
                }
                IconButton(onClick = { anchorDate = anchorDate.plusDays(7) }) {
                    Icon(Icons.Rounded.ChevronRight, contentDescription = "Next week")
                }
            }
        }

        warning?.let {
            Text(
                it,
                color = ClinicalPalette.Muted,
                fontSize = 13.sp,
                modifier = Modifier
                    .fillMaxWidth()
                    .background(ClinicalPalette.Mint, RoundedCornerShape(12.dp))
                    .padding(12.dp),
            )
        }

        when {
            isLoading -> CircularProgressIndicator(modifier = Modifier.align(Alignment.CenterHorizontally))
            byDay.isEmpty() -> Text("No patient appointments in this range.", color = ClinicalPalette.Muted)
            else -> byDay.forEach { (date, rows) ->
                Card(
                    modifier = Modifier.fillMaxWidth(),
                    shape = RoundedCornerShape(16.dp),
                    colors = CardDefaults.cardColors(containerColor = ClinicalPalette.Card),
                ) {
                    Column(
                        modifier = Modifier.padding(14.dp),
                        verticalArrangement = Arrangement.spacedBy(8.dp),
                    ) {
                        Text(date, fontWeight = FontWeight.Bold)
                        rows.forEach { appt ->
                            Column(
                                modifier = Modifier
                                    .fillMaxWidth()
                                    .background(ClinicalPalette.TealSoft.copy(alpha = 0.4f), RoundedCornerShape(12.dp))
                                    .padding(10.dp),
                            ) {
                                Text(
                                    "${appt.start}–${appt.end} · ${appt.patientName}",
                                    fontWeight = FontWeight.SemiBold,
                                    fontSize = 14.sp,
                                )
                                val detail = listOfNotNull(
                                    appt.appointmentType.takeIf { it.isNotBlank() },
                                    appt.serviceSite.takeIf { it.isNotBlank() },
                                    appt.room.takeIf { it.isNotBlank() },
                                    appt.status.takeIf { it.isNotBlank() },
                                ).joinToString(" · ")
                                if (detail.isNotBlank()) {
                                    Text(detail, color = ClinicalPalette.Muted, fontSize = 12.sp)
                                }
                                if (appt.reason.isNotBlank()) {
                                    Text(appt.reason, color = ClinicalPalette.Muted, fontSize = 12.sp)
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
