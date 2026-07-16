package com.midfloridasurgical.calcompose.surgeon

import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.rounded.ArrowDropDown
import androidx.compose.material3.CenterAlignedTopAppBar
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import com.midfloridasurgical.calcompose.data.CalApiClient
import com.midfloridasurgical.calcompose.data.CalSessionStore
import com.midfloridasurgical.calcompose.data.SurgeonHomeStore
import com.midfloridasurgical.calcompose.surgeon.patients.PatientScheduleScreen
import com.midfloridasurgical.calcompose.surgeon.schedule.ScheduleHomeScreen
import com.midfloridasurgical.calcompose.surgeon.timeoff.TimeOffScreen
import com.midfloridasurgical.calcompose.ui.theme.ClinicalPalette

private enum class SurgeonSection(val title: String) {
    SCHEDULE("Schedule"),
    TIME_OFF("Time Off"),
    PATIENTS("Patients"),
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun SurgeonShell(
    apiClient: CalApiClient,
    sessionStore: CalSessionStore,
    token: String,
    deviceToken: String,
) {
    var selectedSection by remember { mutableStateOf(SurgeonSection.SCHEDULE) }
    var menuExpanded by remember { mutableStateOf(false) }
    val homeStore = remember(token, deviceToken) {
        SurgeonHomeStore(apiClient, token, deviceToken)
    }

    Scaffold(
        containerColor = ClinicalPalette.PageTop,
        topBar = {
            CenterAlignedTopAppBar(
                title = {
                    Box {
                        TextButton(onClick = { menuExpanded = true }) {
                            Text(
                                selectedSection.title,
                                color = ClinicalPalette.Ink,
                                fontWeight = FontWeight.Bold,
                            )
                            Icon(
                                Icons.Rounded.ArrowDropDown,
                                contentDescription = "Open section menu",
                                tint = ClinicalPalette.Ink,
                            )
                        }
                        DropdownMenu(
                            expanded = menuExpanded,
                            onDismissRequest = { menuExpanded = false },
                        ) {
                            SurgeonSection.entries.forEach { section ->
                                DropdownMenuItem(
                                    text = { Text(section.title) },
                                    onClick = {
                                        selectedSection = section
                                        menuExpanded = false
                                    },
                                )
                            }
                            HorizontalDivider()
                            DropdownMenuItem(
                                text = { Text("Sign Out") },
                                onClick = {
                                    menuExpanded = false
                                    sessionStore.clear()
                                },
                            )
                        }
                    }
                },
            )
        },
    ) { contentPadding ->
        Box(
            modifier = Modifier
                .fillMaxSize()
                .padding(contentPadding),
        ) {
            when (selectedSection) {
                SurgeonSection.SCHEDULE -> ScheduleHomeScreen(
                    store = homeStore,
                    onOpenPatients = { selectedSection = SurgeonSection.PATIENTS },
                )
                SurgeonSection.TIME_OFF -> TimeOffScreen(store = homeStore)
                SurgeonSection.PATIENTS -> PatientScheduleScreen(
                    apiClient = apiClient,
                    token = token,
                    deviceToken = deviceToken,
                    currentSurgeon = homeStore.currentSurgeon,
                )
            }
        }
    }
}
