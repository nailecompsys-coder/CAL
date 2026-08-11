package com.midfloridasurgical.calcompose.surgeon

import androidx.compose.foundation.background
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
import androidx.compose.material3.TopAppBarDefaults
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import com.midfloridasurgical.calcompose.data.CalApiClient
import com.midfloridasurgical.calcompose.data.CalSessionStore
import com.midfloridasurgical.calcompose.data.SurgeonHomeStore
import com.midfloridasurgical.calcompose.surgeon.alerts.NativeAlertsToolbarButton
import com.midfloridasurgical.calcompose.surgeon.patients.PatientScheduleScreen
import com.midfloridasurgical.calcompose.surgeon.schedule.ScheduleHomeScreen
import com.midfloridasurgical.calcompose.surgeon.timeoff.TimeOffScreen
import com.midfloridasurgical.calcompose.ui.theme.ClinicalPageBackground
import com.midfloridasurgical.calcompose.ui.theme.ClinicalPalette
import com.midfloridasurgical.calcompose.ui.theme.ClinicalTypography

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

    Box(modifier = Modifier.fillMaxSize()) {
        ClinicalPageBackground()

        Scaffold(
            containerColor = ClinicalPalette.Transparent,
            topBar = {
                CenterAlignedTopAppBar(
                    colors = TopAppBarDefaults.centerAlignedTopAppBarColors(
                        containerColor = ClinicalPalette.Teal,
                        scrolledContainerColor = ClinicalPalette.Teal,
                        titleContentColor = ClinicalPalette.OnTeal,
                        actionIconContentColor = ClinicalPalette.OnTeal,
                    ),
                    title = {
                        Box {
                            TextButton(onClick = { menuExpanded = true }) {
                                Text(
                                    selectedSection.title,
                                    style = ClinicalTypography.headlineStrong,
                                    color = ClinicalPalette.OnTeal,
                                )
                                Icon(
                                    Icons.Rounded.ArrowDropDown,
                                    contentDescription = "Open section menu",
                                    tint = ClinicalPalette.OnTeal,
                                )
                            }
                            DropdownMenu(
                                expanded = menuExpanded,
                                onDismissRequest = { menuExpanded = false },
                                modifier = Modifier.background(ClinicalPalette.CardStrong),
                            ) {
                                SurgeonSection.entries.forEach { section ->
                                    DropdownMenuItem(
                                        text = {
                                            Text(
                                                section.title,
                                                style = ClinicalTypography.rowTitleStrong,
                                                color = if (section == selectedSection) {
                                                    ClinicalPalette.Teal
                                                } else {
                                                    ClinicalPalette.Ink
                                                },
                                            )
                                        },
                                        onClick = {
                                            selectedSection = section
                                            menuExpanded = false
                                        },
                                    )
                                }
                                HorizontalDivider(color = ClinicalPalette.Stroke)
                                DropdownMenuItem(
                                    text = {
                                        Text(
                                            "Sign Out",
                                            style = ClinicalTypography.rowTitleStrong,
                                            color = ClinicalPalette.Denied,
                                        )
                                    },
                                    onClick = {
                                        menuExpanded = false
                                        sessionStore.clear()
                                    },
                                )
                            }
                        }
                    },
                    actions = {
                        if (selectedSection != SurgeonSection.PATIENTS) {
                            NativeAlertsToolbarButton(store = homeStore)
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
}
