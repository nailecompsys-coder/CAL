package com.midfloridasurgical.calcompose.surgeon.schedule

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.rounded.ChevronLeft
import androidx.compose.material.icons.rounded.ChevronRight
import androidx.compose.material.icons.rounded.Refresh
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.FilterChip
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
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
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.midfloridasurgical.calcompose.data.SurgeonHomeStore
import com.midfloridasurgical.calcompose.data.models.CallAssignmentUi
import com.midfloridasurgical.calcompose.data.models.ScheduleDayUi
import com.midfloridasurgical.calcompose.data.models.ScheduleItemUi
import com.midfloridasurgical.calcompose.ui.theme.ClinicalPalette
import java.time.LocalDate
import java.time.YearMonth
import java.time.format.DateTimeFormatter
import java.time.format.TextStyle
import java.util.Locale
import kotlinx.coroutines.launch

private enum class ScheduleScope { Day, Week, Month }

@Composable
fun ScheduleHomeScreen(
    store: SurgeonHomeStore,
    onOpenPatients: () -> Unit = {},
) {
    var scheduleScope by remember { mutableStateOf(ScheduleScope.Day) }
    var selectedDate by remember { mutableStateOf(LocalDate.now()) }
    var coveringAssignment by remember { mutableStateOf<CallAssignmentUi?>(null) }
    val coroutineScope = rememberCoroutineScope()

    LaunchedEffect(selectedDate, scheduleScope) {
        val daysAhead = when (scheduleScope) {
            ScheduleScope.Day -> 30L
            ScheduleScope.Week -> 14L
            ScheduleScope.Month -> 45L
        }
        store.refresh(containing = selectedDate, daysAhead = daysAhead)
    }

    val selectedDay = store.day(selectedDate)
    val weekDays = store.week(selectedDate)
    val month = YearMonth.from(selectedDate)

    Column(
        modifier = Modifier
            .fillMaxSize()
            .background(
                Brush.linearGradient(
                    listOf(ClinicalPalette.PageTop, ClinicalPalette.PageBottom),
                ),
            ),
    ) {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(horizontal = 12.dp, vertical = 8.dp),
            horizontalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            ScheduleScope.entries.forEach { option ->
                FilterChip(
                    selected = scheduleScope == option,
                    onClick = { scheduleScope = option },
                    label = { Text(option.name) },
                )
            }
            Spacer(modifier = Modifier.weight(1f))
            IconButton(
                onClick = {
                    coroutineScope.launch { store.refresh(containing = selectedDate) }
                },
            ) {
                Icon(Icons.Rounded.Refresh, contentDescription = "Refresh")
            }
        }

        DateStepper(
            title = stepperTitle(scheduleScope, selectedDate, weekDays),
            subtitle = when (scheduleScope) {
                ScheduleScope.Day -> selectedDate.year.toString()
                ScheduleScope.Week -> "Week"
                ScheduleScope.Month -> "Month"
            },
            onPrevious = {
                selectedDate = when (scheduleScope) {
                    ScheduleScope.Day -> selectedDate.minusDays(1)
                    ScheduleScope.Week -> selectedDate.minusWeeks(1)
                    ScheduleScope.Month -> selectedDate.minusMonths(1)
                }
            },
            onNext = {
                selectedDate = when (scheduleScope) {
                    ScheduleScope.Day -> selectedDate.plusDays(1)
                    ScheduleScope.Week -> selectedDate.plusWeeks(1)
                    ScheduleScope.Month -> selectedDate.plusMonths(1)
                }
            },
            onToday = { selectedDate = LocalDate.now() },
            showToday = selectedDate != LocalDate.now(),
        )

        when {
            store.isLoading && store.days.isEmpty() -> {
                Box(
                    modifier = Modifier.fillMaxSize(),
                    contentAlignment = Alignment.Center,
                ) {
                    CircularProgressIndicator()
                }
            }
            else -> {
                Column(
                    modifier = Modifier
                        .fillMaxSize()
                        .verticalScroll(rememberScrollState())
                        .padding(horizontal = 16.dp, vertical = 8.dp),
                    verticalArrangement = Arrangement.spacedBy(10.dp),
                ) {
                    store.warningMessage?.let { WarningBanner(it) }

                    when (scheduleScope) {
                        ScheduleScope.Day -> DayDashboard(
                            day = selectedDay,
                            onCover = { coveringAssignment = it },
                            onOpenPatients = onOpenPatients,
                        )
                        ScheduleScope.Week -> weekDays.forEach { day ->
                            WeekDayCard(
                                day = day,
                                onSelect = {
                                    selectedDate = day.date
                                    scheduleScope = ScheduleScope.Day
                                },
                                onCover = { coveringAssignment = it },
                            )
                        }
                        ScheduleScope.Month -> {
                            MonthGrid(
                                month = month,
                                selectedDate = selectedDate,
                                dayFor = store::day,
                                onSelect = {
                                    selectedDate = it
                                    scheduleScope = ScheduleScope.Day
                                },
                            )
                            DayDashboard(
                                day = selectedDay,
                                onCover = { coveringAssignment = it },
                                onOpenPatients = onOpenPatients,
                            )
                        }
                    }
                    Spacer(modifier = Modifier.height(16.dp))
                }
            }
        }
    }

    coveringAssignment?.let { assignment ->
        CallCoverageSheet(
            assignment = assignment,
            surgeons = store.eligibleCoveringSurgeons(
                originalSurgeonId = assignment.originalSurgeonId,
                fallbackStaffType = store.currentSurgeon?.staffType,
            ),
            isSaving = store.isLoading,
            onDismiss = { coveringAssignment = null },
            onSave = { surgeonId ->
                coroutineScope.launch {
                    runCatching {
                        store.submitCallCoverage(assignment.rotationId, surgeonId)
                        coveringAssignment = null
                    }.onFailure {
                        store.warningMessage = it.message
                    }
                }
            },
        )
    }
}

@Composable
private fun DateStepper(
    title: String,
    subtitle: String,
    onPrevious: () -> Unit,
    onNext: () -> Unit,
    onToday: () -> Unit,
    showToday: Boolean,
) {
    Card(
        modifier = Modifier
            .fillMaxWidth()
            .padding(horizontal = 16.dp),
        shape = RoundedCornerShape(16.dp),
        colors = CardDefaults.cardColors(containerColor = ClinicalPalette.Card),
    ) {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(horizontal = 4.dp, vertical = 6.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            IconButton(onClick = onPrevious) {
                Icon(Icons.Rounded.ChevronLeft, contentDescription = "Previous")
            }
            Column(
                modifier = Modifier.weight(1f),
                horizontalAlignment = Alignment.CenterHorizontally,
            ) {
                Text(title, fontWeight = FontWeight.SemiBold, maxLines = 1, overflow = TextOverflow.Ellipsis)
                Text(subtitle, color = ClinicalPalette.Muted, fontSize = 12.sp)
            }
            if (showToday) {
                TextButton(onClick = onToday) { Text("Today") }
            }
            IconButton(onClick = onNext) {
                Icon(Icons.Rounded.ChevronRight, contentDescription = "Next")
            }
        }
    }
}

@Composable
private fun DayDashboard(
    day: ScheduleDayUi,
    onCover: (CallAssignmentUi) -> Unit,
    onOpenPatients: () -> Unit,
) {
    SectionCard("On call / Off") {
        if (day.assignments.isEmpty()) {
            Text("No on-call coverage", color = ClinicalPalette.Muted, fontSize = 13.sp)
        } else {
            day.assignments.forEach { assignment ->
                Row(
                    modifier = Modifier
                        .fillMaxWidth()
                        .clickable { onCover(assignment) }
                        .padding(vertical = 4.dp),
                    horizontalArrangement = Arrangement.SpaceBetween,
                ) {
                    Column(modifier = Modifier.weight(1f)) {
                        Text(assignment.group, fontWeight = FontWeight.SemiBold)
                        Text(
                            if (assignment.isCovered) {
                                "${assignment.displayInitials} covering for ${assignment.originalInitials}"
                            } else {
                                assignment.displayInitials
                            },
                            color = ClinicalPalette.Muted,
                            fontSize = 12.sp,
                        )
                    }
                    Text("Cover", color = ClinicalPalette.Teal, fontWeight = FontWeight.Bold)
                }
            }
        }
        if (day.off.isNotEmpty()) {
            Text("Off: ${day.off.joinToString(" ")}", fontSize = 13.sp)
        }
        if (day.requestedOff.isNotEmpty()) {
            Text(
                "Requested: ${day.requestedOff.joinToString(" ")}",
                fontSize = 13.sp,
                color = ClinicalPalette.Muted,
            )
        }
        if (day.hasMyApprovedOff) {
            Text("You are off today", color = ClinicalPalette.Teal, fontWeight = FontWeight.Bold)
        }
    }

    SectionCard("Clinic / OR Schedule") {
        if (day.mySchedule.isEmpty()) {
            Text("No clinic or hospital schedule", color = ClinicalPalette.Muted, fontSize = 13.sp)
        } else {
            day.mySchedule.forEach { item ->
                ScheduleItemRow(item)
            }
            TextButton(onClick = onOpenPatients) {
                Text("Open Patients")
            }
        }
    }

    SectionCard("Meetings") {
        if (day.meetings.isEmpty()) {
            Text("none", color = ClinicalPalette.Muted, fontSize = 13.sp)
        } else {
            day.meetings.forEach { ScheduleItemRow(it) }
        }
    }

    if (day.personalItems.isNotEmpty()) {
        SectionCard("Personal") {
            day.personalItems.forEach {
                Text(it, fontSize = 13.sp)
            }
        }
    }
}

@Composable
private fun WeekDayCard(
    day: ScheduleDayUi,
    onSelect: () -> Unit,
    onCover: (CallAssignmentUi) -> Unit,
) {
    Card(
        modifier = Modifier
            .fillMaxWidth()
            .clickable(onClick = onSelect),
        shape = RoundedCornerShape(16.dp),
        colors = CardDefaults.cardColors(containerColor = ClinicalPalette.Card),
    ) {
        Column(
            modifier = Modifier.padding(14.dp),
            verticalArrangement = Arrangement.spacedBy(6.dp),
        ) {
            Text(
                "${day.weekdayShort} · ${day.date.format(DateTimeFormatter.ofPattern("MMM d"))}",
                fontWeight = FontWeight.Bold,
            )
            day.assignments.forEach { assignment ->
                Text(
                    "${assignment.group}: ${assignment.displayInitials}",
                    fontSize = 13.sp,
                    modifier = Modifier.clickable { onCover(assignment) },
                )
            }
            if (day.mySchedule.isNotEmpty()) {
                Text(
                    day.mySchedule.joinToString(" · ") { it.title },
                    color = ClinicalPalette.Muted,
                    fontSize = 12.sp,
                    maxLines = 2,
                    overflow = TextOverflow.Ellipsis,
                )
            }
            if (day.off.isNotEmpty()) {
                Text("Off ${day.off.joinToString(" ")}", fontSize = 12.sp)
            }
        }
    }
}

@Composable
private fun MonthGrid(
    month: YearMonth,
    selectedDate: LocalDate,
    dayFor: (LocalDate) -> ScheduleDayUi,
    onSelect: (LocalDate) -> Unit,
) {
    val first = month.atDay(1)
    val leading = first.dayOfWeek.value % 7
    val daysInMonth = month.lengthOfMonth()
    Card(
        modifier = Modifier.fillMaxWidth(),
        shape = RoundedCornerShape(16.dp),
        colors = CardDefaults.cardColors(containerColor = ClinicalPalette.Card),
    ) {
        Column(
            modifier = Modifier.padding(10.dp),
            verticalArrangement = Arrangement.spacedBy(4.dp),
        ) {
            Row(modifier = Modifier.fillMaxWidth()) {
                listOf("S", "M", "T", "W", "T", "F", "S").forEach { label ->
                    Text(
                        label,
                        modifier = Modifier.weight(1f),
                        textAlign = TextAlign.Center,
                        color = ClinicalPalette.Muted,
                        fontSize = 11.sp,
                        fontWeight = FontWeight.Bold,
                    )
                }
            }
            var dayNumber = 1
            repeat(6) { week ->
                if (dayNumber > daysInMonth) return@repeat
                Row(modifier = Modifier.fillMaxWidth()) {
                    repeat(7) { column ->
                        val cellIndex = week * 7 + column
                        if (cellIndex < leading || dayNumber > daysInMonth) {
                            Spacer(
                                modifier = Modifier
                                    .weight(1f)
                                    .aspectRatio(1f),
                            )
                        } else {
                            val date = month.atDay(dayNumber)
                            val day = dayFor(date)
                            val selected = date == selectedDate
                            Column(
                                modifier = Modifier
                                    .weight(1f)
                                    .aspectRatio(1f)
                                    .padding(2.dp)
                                    .background(
                                        if (selected) {
                                            ClinicalPalette.TealSoft
                                        } else {
                                            ClinicalPalette.Mint.copy(alpha = 0.35f)
                                        },
                                        RoundedCornerShape(8.dp),
                                    )
                                    .clickable { onSelect(date) }
                                    .padding(2.dp),
                                horizontalAlignment = Alignment.CenterHorizontally,
                            ) {
                                Text(
                                    dayNumber.toString(),
                                    fontSize = 12.sp,
                                    fontWeight = if (selected) FontWeight.Bold else FontWeight.SemiBold,
                                    color = if (selected) ClinicalPalette.Teal else ClinicalPalette.Ink,
                                )
                                val marks = buildList {
                                    if (day.assignments.isNotEmpty()) add("C")
                                    if (day.mySchedule.isNotEmpty()) add("S")
                                    if (day.off.isNotEmpty() || day.hasMyApprovedOff) add("O")
                                }.joinToString("")
                                if (marks.isNotEmpty()) {
                                    Text(marks, fontSize = 9.sp, color = ClinicalPalette.Muted, maxLines = 1)
                                }
                            }
                            dayNumber += 1
                        }
                    }
                }
            }
        }
    }
}

@Composable
private fun SectionCard(title: String, content: @Composable () -> Unit) {
    Card(
        modifier = Modifier.fillMaxWidth(),
        shape = RoundedCornerShape(16.dp),
        colors = CardDefaults.cardColors(containerColor = ClinicalPalette.Card),
    ) {
        Column(
            modifier = Modifier.padding(14.dp),
            verticalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            Text(title, color = ClinicalPalette.Muted, fontSize = 12.sp, fontWeight = FontWeight.Bold)
            content()
        }
    }
}

@Composable
private fun ScheduleItemRow(item: ScheduleItemUi) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .background(ClinicalPalette.TealSoft.copy(alpha = 0.45f), RoundedCornerShape(12.dp))
            .padding(10.dp),
        horizontalArrangement = Arrangement.spacedBy(10.dp),
    ) {
        Text(item.period, color = ClinicalPalette.Teal, fontWeight = FontWeight.Bold, fontSize = 12.sp)
        Column(modifier = Modifier.weight(1f)) {
            Text(item.title, fontWeight = FontWeight.SemiBold, fontSize = 14.sp)
            if (item.subtitle.isNotBlank()) {
                Text(item.subtitle, color = ClinicalPalette.Muted, fontSize = 12.sp)
            }
            if (item.timeRange.isNotBlank()) {
                Text(item.timeRange, color = ClinicalPalette.Muted, fontSize = 12.sp)
            }
        }
    }
}

@Composable
private fun WarningBanner(message: String) {
    Text(
        message,
        color = ClinicalPalette.Muted,
        fontSize = 13.sp,
        modifier = Modifier
            .fillMaxWidth()
            .background(ClinicalPalette.Mint, RoundedCornerShape(12.dp))
            .padding(12.dp),
    )
}

private fun stepperTitle(
    scheduleScope: ScheduleScope,
    selectedDate: LocalDate,
    weekDays: List<ScheduleDayUi>,
): String {
    val monthDay = DateTimeFormatter.ofPattern("MMM d", Locale.US)
    return when (scheduleScope) {
        ScheduleScope.Day -> {
            if (selectedDate == LocalDate.now()) {
                "Today · ${selectedDate.format(monthDay)}"
            } else {
                "${selectedDate.dayOfWeek.getDisplayName(TextStyle.FULL, Locale.US)} · ${selectedDate.format(monthDay)}"
            }
        }
        ScheduleScope.Week -> {
            val start = weekDays.firstOrNull()?.date ?: selectedDate
            val end = weekDays.lastOrNull()?.date ?: selectedDate
            "${start.format(monthDay)} – ${end.format(monthDay)}"
        }
        ScheduleScope.Month -> {
            selectedDate.month.getDisplayName(TextStyle.FULL, Locale.US) + " ${selectedDate.year}"
        }
    }
}
