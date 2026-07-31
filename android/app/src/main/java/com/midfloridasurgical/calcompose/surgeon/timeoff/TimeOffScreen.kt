package com.midfloridasurgical.calcompose.surgeon.timeoff

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.rounded.Add
import androidx.compose.material.icons.rounded.ChevronLeft
import androidx.compose.material.icons.rounded.ChevronRight
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
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
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.midfloridasurgical.calcompose.data.SurgeonHomeStore
import com.midfloridasurgical.calcompose.data.models.NativeDayOffRequest
import com.midfloridasurgical.calcompose.ui.theme.ClinicalPalette
import com.midfloridasurgical.calcompose.ui.theme.ClinicalTypography
import com.midfloridasurgical.calcompose.ui.theme.LiquidGlassCard
import java.time.LocalDate
import java.time.YearMonth
import java.time.format.DateTimeFormatter
import java.time.format.TextStyle
import java.util.Locale

@Composable
fun TimeOffScreen(store: SurgeonHomeStore) {
    val todayMonth = remember { YearMonth.now() }
    var selectedMonth by remember { mutableStateOf(todayMonth) }
    var showRequestSheet by remember { mutableStateOf(false) }
    var showingMonthMenu by remember { mutableStateOf(false) }

    val months = remember {
        (-1 until 12).map { todayMonth.plusMonths(it.toLong()) }
    }

    // Appear: first of current month + 365 (iOS TimeOffHomeView.task)
    LaunchedEffect(Unit) {
        store.loadLookahead(containing = todayMonth.atDay(1), daysAhead = 365)
    }

    // Month change: containing month start + 62
    LaunchedEffect(selectedMonth) {
        store.loadLookahead(containing = selectedMonth.atDay(1), daysAhead = 62)
    }

    val ganttDays = remember(selectedMonth, store.days) {
        (1..selectedMonth.lengthOfMonth()).map { day ->
            val date = selectedMonth.atDay(day)
            store.day(date)
        }
    }
    val ganttModel = remember(selectedMonth, ganttDays, store.surgeons) {
        TimeOffGanttModel.build(
            month = selectedMonth,
            days = ganttDays,
            surgeons = store.surgeons,
        )
    }

    val monthStart = selectedMonth.atDay(1).toString()
    val monthEnd = selectedMonth.atEndOfMonth().toString()
    val monthRequests = remember(selectedMonth, store.requests) {
        store.requests
            .filter { it.startDate <= monthEnd && it.endDate >= monthStart }
            .sortedWith(compareBy({ it.startDate }, { it.id }))
    }

    val monthLabel = selectedMonth.format(DateTimeFormatter.ofPattern("MMM yyyy", Locale.US))
    val monthWide = selectedMonth.month.getDisplayName(TextStyle.FULL, Locale.US) +
        " ${selectedMonth.year}"

    Column(
        modifier = Modifier
            .fillMaxSize()
            .background(
                Brush.linearGradient(
                    listOf(
                        ClinicalPalette.PageTop,
                        ClinicalPalette.PageMiddle,
                        ClinicalPalette.PageBottom,
                    ),
                ),
            )
            .verticalScroll(rememberScrollState())
            .padding(horizontal = 16.dp, vertical = 8.dp),
        verticalArrangement = Arrangement.spacedBy(10.dp),
    ) {
        Button(
            onClick = { showRequestSheet = true },
            modifier = Modifier.fillMaxWidth(),
            colors = ButtonDefaults.buttonColors(
                containerColor = ClinicalPalette.Teal,
                contentColor = ClinicalPalette.OnTeal,
            ),
            shape = RoundedCornerShape(12.dp),
        ) {
            Icon(Icons.Rounded.Add, contentDescription = null)
            Spacer(modifier = Modifier.size(6.dp))
            Text("Request Time Off", style = ClinicalTypography.rowTitle)
        }

        store.warningMessage?.let {
            LiquidGlassCard(tint = ClinicalPalette.Amber, cornerRadius = 14.dp) {
                Text(
                    it,
                    color = ClinicalPalette.Muted,
                    style = ClinicalTypography.caption,
                    modifier = Modifier.padding(12.dp),
                )
            }
        }

        LiquidGlassCard(tint = ClinicalPalette.TealSoft, cornerRadius = 16.dp) {
            Column(
                modifier = Modifier.padding(14.dp),
                verticalArrangement = Arrangement.spacedBy(10.dp),
            ) {
                Text(
                    "WHO'S OUT",
                    style = ClinicalTypography.sectionLabel,
                    color = ClinicalPalette.Muted,
                )

                MonthStepper(
                    title = monthWide,
                    subtitle = "Practice coverage",
                    onPrevious = { selectedMonth = selectedMonth.minusMonths(1) },
                    onNext = { selectedMonth = selectedMonth.plusMonths(1) },
                    onTitleTap = { showingMonthMenu = true },
                    menuExpanded = showingMonthMenu,
                    onDismissMenu = { showingMonthMenu = false },
                    months = months,
                    onSelectMonth = {
                        selectedMonth = it
                        showingMonthMenu = false
                    },
                )

                if (store.isLoading && store.days.isEmpty()) {
                    Box(
                        modifier = Modifier
                            .fillMaxWidth()
                            .height(80.dp),
                        contentAlignment = Alignment.Center,
                    ) {
                        CircularProgressIndicator(color = ClinicalPalette.Teal)
                    }
                } else {
                    TimeOffGanttView(model = ganttModel, selectedMonth = selectedMonth)
                }

                Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
                    Text(
                        "MY REQUESTS · ${monthLabel.uppercase(Locale.US)}",
                        style = ClinicalTypography.sectionLabel,
                        color = ClinicalPalette.Muted,
                    )
                    if (monthRequests.isEmpty()) {
                        Text(
                            "No requests in $monthLabel.",
                            color = ClinicalPalette.Muted,
                            style = ClinicalTypography.caption,
                            modifier = Modifier.padding(vertical = 4.dp),
                        )
                    } else {
                        monthRequests.forEach { request ->
                            TimeOffRequestRow(request)
                        }
                    }
                }
            }
        }

        Spacer(modifier = Modifier.height(18.dp))
    }

    if (showRequestSheet) {
        TimeOffRequestSheet(
            onDismiss = { showRequestSheet = false },
            onSubmit = { start, end, reason, notes, segments ->
                store.submitTimeOff(
                    start = start,
                    end = end,
                    reason = reason,
                    notes = notes,
                    segments = segments,
                )
            },
        )
    }
}

@Composable
private fun MonthStepper(
    title: String,
    subtitle: String,
    onPrevious: () -> Unit,
    onNext: () -> Unit,
    onTitleTap: () -> Unit,
    menuExpanded: Boolean,
    onDismissMenu: () -> Unit,
    months: List<YearMonth>,
    onSelectMonth: (YearMonth) -> Unit,
) {
    LiquidGlassCard(tint = ClinicalPalette.Card, cornerRadius = 16.dp) {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(horizontal = 4.dp, vertical = 6.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            IconButton(onClick = onPrevious) {
                Icon(Icons.Rounded.ChevronLeft, contentDescription = "Previous month")
            }
            Box(
                modifier = Modifier
                    .weight(1f)
                    .clickable(onClick = onTitleTap),
                contentAlignment = Alignment.Center,
            ) {
                Column(horizontalAlignment = Alignment.CenterHorizontally) {
                    Text(
                        title,
                        style = ClinicalTypography.rowTitle,
                        color = ClinicalPalette.Ink,
                        maxLines = 1,
                        overflow = TextOverflow.Ellipsis,
                    )
                    Text(
                        subtitle,
                        color = ClinicalPalette.Muted,
                        style = ClinicalTypography.captionEmphasized,
                    )
                }
                DropdownMenu(
                    expanded = menuExpanded,
                    onDismissRequest = onDismissMenu,
                ) {
                    months.forEach { month ->
                        DropdownMenuItem(
                            text = {
                                Text(
                                    month.month.getDisplayName(TextStyle.FULL, Locale.US) +
                                        " ${month.year}",
                                    style = ClinicalTypography.rowTitle,
                                )
                            },
                            onClick = { onSelectMonth(month) },
                        )
                    }
                }
            }
            IconButton(onClick = onNext) {
                Icon(Icons.Rounded.ChevronRight, contentDescription = "Next month")
            }
        }
    }
}

@Composable
private fun TimeOffRequestRow(request: NativeDayOffRequest) {
    val status = request.status.ifBlank { "pending" }
    val statusColor = when (status.lowercase(Locale.US)) {
        "approved" -> ClinicalPalette.Teal
        "denied" -> ClinicalPalette.Denied
        else -> ClinicalPalette.WarningText
    }
    val dateRange = if (request.startDate == request.endDate) {
        formatShortDate(request.startDate)
    } else {
        "${formatShortDate(request.startDate)} - ${formatShortDate(request.endDate)}"
    }

    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.spacedBy(8.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Box(
            modifier = Modifier
                .size(8.dp)
                .background(statusColor, CircleShape),
        )
        Text(
            dateRange,
            style = ClinicalTypography.caption,
            color = ClinicalPalette.Ink,
            maxLines = 1,
        )
        Text(
            request.reason.ifBlank { "Time off" },
            style = ClinicalTypography.caption,
            color = ClinicalPalette.Muted,
            maxLines = 1,
            overflow = TextOverflow.Ellipsis,
            modifier = Modifier.weight(1f),
        )
        Text(
            status.replaceFirstChar { if (it.isLowerCase()) it.titlecase(Locale.US) else it.toString() },
            style = ClinicalTypography.badge,
            color = statusColor,
        )
    }
}

private fun formatShortDate(iso: String): String {
    val date = runCatching { LocalDate.parse(iso) }.getOrNull() ?: return iso
    return date.format(DateTimeFormatter.ofPattern("MM/dd", Locale.US))
}
