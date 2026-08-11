package com.midfloridasurgical.calcompose.surgeon.alerts

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.rounded.Notifications
import androidx.compose.material.icons.rounded.NotificationsNone
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.rememberModalBottomSheetState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.midfloridasurgical.calcompose.data.SurgeonHomeStore
import com.midfloridasurgical.calcompose.data.models.NativeScheduleAlert
import com.midfloridasurgical.calcompose.ui.theme.ClinicalPalette
import com.midfloridasurgical.calcompose.ui.theme.ClinicalTypography
import com.midfloridasurgical.calcompose.ui.theme.WhiteboardCard
import java.time.LocalDateTime
import java.time.OffsetDateTime
import java.time.format.DateTimeFormatter
import java.util.Locale
import kotlinx.coroutines.launch

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun NativeAlertsToolbarButton(store: SurgeonHomeStore) {
    var showingAlerts by remember { mutableStateOf(false) }
    val unreadCount = store.alerts.unreadCount
    val scope = rememberCoroutineScope()
    val sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = true)

    Box {
        IconButton(onClick = { showingAlerts = true }) {
            Icon(
                imageVector = if (unreadCount > 0) {
                    Icons.Rounded.Notifications
                } else {
                    Icons.Rounded.NotificationsNone
                },
                contentDescription = if (unreadCount > 0) {
                    "Alerts, $unreadCount unread"
                } else {
                    "Alerts"
                },
                tint = ClinicalPalette.OnTeal,
            )
        }
        if (unreadCount > 0) {
            Text(
                text = if (unreadCount > 9) "9+" else unreadCount.toString(),
                style = ClinicalTypography.badge,
                color = ClinicalPalette.OnTeal,
                modifier = Modifier
                    .align(Alignment.TopEnd)
                    .padding(top = 6.dp, end = 4.dp)
                    .background(ClinicalPalette.Urgency, RoundedCornerShape(50))
                    .padding(horizontal = 4.dp, vertical = 1.dp),
            )
        }
    }

    if (showingAlerts) {
        ModalBottomSheet(
            onDismissRequest = { showingAlerts = false },
            sheetState = sheetState,
            containerColor = ClinicalPalette.PageMiddle,
        ) {
            AlertInbox(
                alerts = store.alerts.recent,
                onClose = { showingAlerts = false },
                onMarkRead = {
                    showingAlerts = false
                    scope.launch { store.markAlertsRead() }
                },
            )
        }
    }
}

@Composable
private fun AlertInbox(
    alerts: List<NativeScheduleAlert>,
    onClose: () -> Unit,
    onMarkRead: () -> Unit,
) {
    val allRead = alerts.isEmpty() || alerts.all { it.isRead }
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .padding(horizontal = 16.dp)
            .padding(bottom = 28.dp),
    ) {
        Row(
            modifier = Modifier.fillMaxWidth(),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            TextButton(onClick = onClose) {
                Text("Close", color = ClinicalPalette.Muted)
            }
            Spacer(modifier = Modifier.weight(1f))
            Text(
                "CAL Alerts",
                style = ClinicalTypography.headline,
                color = ClinicalPalette.Ink,
            )
            Spacer(modifier = Modifier.weight(1f))
            TextButton(onClick = onMarkRead, enabled = !allRead) {
                Text(
                    "Mark Read",
                    color = if (allRead) ClinicalPalette.Muted else ClinicalPalette.Teal,
                    fontWeight = FontWeight.SemiBold,
                )
            }
        }
        Spacer(modifier = Modifier.height(8.dp))
        if (alerts.isEmpty()) {
            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(vertical = 24.dp),
                horizontalArrangement = Arrangement.spacedBy(10.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Icon(
                    Icons.Rounded.NotificationsNone,
                    contentDescription = null,
                    tint = ClinicalPalette.Muted,
                    modifier = Modifier.size(22.dp),
                )
                Text("No CAL alerts", color = ClinicalPalette.Muted, style = ClinicalTypography.rowTitle)
            }
        } else {
            LazyColumn(verticalArrangement = Arrangement.spacedBy(10.dp)) {
                items(alerts, key = { it.id }) { alert ->
                    AlertRow(alert)
                }
            }
        }
    }
}

@Composable
private fun AlertRow(alert: NativeScheduleAlert) {
    WhiteboardCard(
        tint = if (alert.isRead) ClinicalPalette.CardStrong else ClinicalPalette.TealSoft,
        cornerRadius = 12.dp,
    ) {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .padding(12.dp),
            verticalArrangement = Arrangement.spacedBy(4.dp),
        ) {
            Row(verticalAlignment = Alignment.Top) {
                if (!alert.isRead) {
                    Box(
                        modifier = Modifier
                            .padding(top = 5.dp, end = 8.dp)
                            .size(7.dp)
                            .background(ClinicalPalette.Teal, CircleShape),
                    )
                }
                Column(modifier = Modifier.weight(1f)) {
                    Text(
                        alert.title,
                        style = if (alert.isRead) {
                            ClinicalTypography.rowTitle
                        } else {
                            ClinicalTypography.rowTitleStrong
                        },
                        color = ClinicalPalette.Ink,
                    )
                    Text(alert.body, style = ClinicalTypography.caption, color = ClinicalPalette.Muted)
                }
                val display = alertDisplayTime(alert.createdAt)
                if (display.isNotEmpty()) {
                    Text(
                        display,
                        style = ClinicalTypography.captionEmphasized,
                        color = ClinicalPalette.Muted,
                    )
                }
            }
        }
    }
}

private fun alertDisplayTime(createdAt: String): String {
    if (createdAt.isBlank()) return ""
    val local = runCatching {
        OffsetDateTime.parse(createdAt).toLocalDateTime()
    }.recoverCatching {
        LocalDateTime.parse(createdAt)
    }.getOrNull() ?: return ""
    return local.format(DateTimeFormatter.ofPattern("MMM d, h:mm a", Locale.US))
}
