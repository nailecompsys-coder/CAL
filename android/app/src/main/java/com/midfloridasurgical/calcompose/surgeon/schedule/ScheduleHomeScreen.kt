package com.midfloridasurgical.calcompose.surgeon.schedule

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.rounded.Add
import androidx.compose.material.icons.rounded.ChevronLeft
import androidx.compose.material.icons.rounded.ChevronRight
import androidx.compose.material.icons.rounded.Refresh
import androidx.compose.material3.CircularProgressIndicator
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
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.midfloridasurgical.calcompose.data.SurgeonHomeStore
import com.midfloridasurgical.calcompose.data.models.CallAssignmentUi
import com.midfloridasurgical.calcompose.data.models.PersonalItemUi
import com.midfloridasurgical.calcompose.data.models.ScheduleDayUi
import com.midfloridasurgical.calcompose.data.models.ScheduleItemUi
import com.midfloridasurgical.calcompose.ui.theme.ClinicalPalette
import com.midfloridasurgical.calcompose.ui.theme.ClinicalScopeChip
import com.midfloridasurgical.calcompose.ui.theme.ClinicalTodayChip
import com.midfloridasurgical.calcompose.ui.theme.ClinicalTypography
import com.midfloridasurgical.calcompose.ui.theme.DashboardSection
import com.midfloridasurgical.calcompose.ui.theme.WhiteboardCard
import com.midfloridasurgical.calcompose.ui.theme.clinicalPageBackground
import com.midfloridasurgical.calcompose.util.isBenignCancel
import com.midfloridasurgical.calcompose.util.onFailureUnlessCancelled
import java.time.DayOfWeek
import java.time.LocalDate
import java.time.YearMonth
import java.time.format.DateTimeFormatter
import java.time.format.TextStyle
import java.time.temporal.TemporalAdjusters
import java.util.Locale
import kotlinx.coroutines.delay
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
    var editingPersonal by remember { mutableStateOf<PersonalItemUi?>(null) }
    var showingPersonalEditor by remember { mutableStateOf(false) }
    val coroutineScope = rememberCoroutineScope()

    LaunchedEffect(selectedDate, scheduleScope) {
        delay(120)
        when (scheduleScope) {
            ScheduleScope.Day -> store.loadLookahead(containing = selectedDate, daysAhead = 30)
            ScheduleScope.Week -> store.refresh(containing = selectedDate, daysAhead = 14)
            ScheduleScope.Month -> store.refresh(containing = selectedDate, daysAhead = 45)
        }
    }

    val selectedDay = remember(selectedDate, store.days) { store.day(selectedDate) }
    val weekDays = remember(selectedDate, store.days) { store.week(selectedDate) }
    val month = remember(selectedDate) { YearMonth.from(selectedDate) }
    val coveringSurgeons = remember(coveringAssignment, store.surgeons, store.currentSurgeon) {
        coveringAssignment?.let { assignment ->
            store.eligibleCoveringSurgeons(
                originalSurgeonId = assignment.originalSurgeonId,
                fallbackStaffType = store.currentSurgeon?.staffType,
            )
        }.orEmpty()
    }

    Column(
        modifier = Modifier
            .fillMaxSize()
            .clinicalPageBackground(),
    ) {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(horizontal = 12.dp, vertical = 10.dp),
            horizontalArrangement = Arrangement.spacedBy(8.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            ScheduleScope.entries.forEach { option ->
                ClinicalScopeChip(
                    selected = scheduleScope == option,
                    label = option.name,
                    onClick = { scheduleScope = option },
                )
            }
            Spacer(modifier = Modifier.weight(1f))
            IconButton(
                onClick = {
                    coroutineScope.launch {
                        when (scheduleScope) {
                            ScheduleScope.Day ->
                                store.loadLookahead(
                                    containing = selectedDate,
                                    daysAhead = 30,
                                    force = true,
                                )
                            else -> store.refresh(containing = selectedDate, force = true)
                        }
                    }
                },
                modifier = Modifier.size(48.dp),
            ) {
                Icon(
                    Icons.Rounded.Refresh,
                    contentDescription = "Refresh",
                    tint = ClinicalPalette.Teal,
                )
            }
        }

        DateStepper(
            title = stepperTitle(scheduleScope, selectedDate, weekDays),
            subtitle = when (scheduleScope) {
                ScheduleScope.Day -> selectedDate.year.toString()
                ScheduleScope.Week -> "Week timeline"
                ScheduleScope.Month -> "Month heatmap"
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
                    CircularProgressIndicator(color = ClinicalPalette.Teal)
                }
            }
            else -> {
                LazyColumn(
                    modifier = Modifier
                        .fillMaxSize()
                        .padding(horizontal = 14.dp),
                    verticalArrangement = Arrangement.spacedBy(12.dp),
                    contentPadding = PaddingValues(top = 10.dp, bottom = 20.dp),
                ) {
                    store.warningMessage?.let { message ->
                        item(key = "warning") { WarningBanner(message) }
                    }

                    when (scheduleScope) {
                        ScheduleScope.Day -> {
                            item(key = "day-${selectedDay.date}") {
                                DayDashboard(
                                    day = selectedDay,
                                    onCover = { coveringAssignment = it },
                                    onOpenPatients = onOpenPatients,
                                    onAddPersonal = {
                                        editingPersonal = null
                                        showingPersonalEditor = true
                                    },
                                    onEditPersonal = {
                                        editingPersonal = it
                                        showingPersonalEditor = true
                                    },
                                )
                            }
                        }
                        ScheduleScope.Week -> {
                            item(key = "week-rail") {
                                WeekTimeline(
                                    days = weekDays,
                                    selectedDate = selectedDate,
                                    onSelect = {
                                        selectedDate = it
                                        scheduleScope = ScheduleScope.Day
                                    },
                                    onCover = { coveringAssignment = it },
                                )
                            }
                        }
                        ScheduleScope.Month -> {
                            item(key = "month-${month}") {
                                MonthGrid(
                                    month = month,
                                    selectedDate = selectedDate,
                                    dayFor = store::day,
                                    onSelect = { selectedDate = it },
                                )
                            }
                            item(key = "month-day-${selectedDay.date}") {
                                DayDashboard(
                                    day = selectedDay,
                                    onCover = { coveringAssignment = it },
                                    onOpenPatients = onOpenPatients,
                                    onAddPersonal = {
                                        editingPersonal = null
                                        showingPersonalEditor = true
                                    },
                                    onEditPersonal = {
                                        editingPersonal = it
                                        showingPersonalEditor = true
                                    },
                                )
                            }
                        }
                    }
                }
            }
        }
    }

    coveringAssignment?.let { assignment ->
        CallCoverageSheet(
            assignment = assignment,
            surgeons = coveringSurgeons,
            isSaving = store.isLoading,
            onDismiss = { coveringAssignment = null },
            onSave = { surgeonId ->
                coroutineScope.launch {
                    runCatching {
                        store.submitCallCoverage(assignment.rotationId, surgeonId)
                        coveringAssignment = null
                    }.onFailureUnlessCancelled { e ->
                        if (e.isBenignCancel()) return@onFailureUnlessCancelled
                        store.warningMessage = e.message
                    }
                }
            },
            onClearCoverage = assignment.coverageId?.let { coverageId ->
                {
                    coroutineScope.launch {
                        runCatching {
                            store.cancelCallCoverage(coverageId)
                            coveringAssignment = null
                        }.onFailureUnlessCancelled { e ->
                            if (e.isBenignCancel()) return@onFailureUnlessCancelled
                            store.warningMessage = e.message
                        }
                    }
                }
            },
        )
    }

    if (showingPersonalEditor) {
        PersonalItemEditorSheet(
            date = selectedDate,
            item = editingPersonal,
            onDismiss = {
                showingPersonalEditor = false
                editingPersonal = null
            },
            onSave = { title, notes, start, end ->
                if (editingPersonal != null) {
                    store.updatePersonalItem(
                        itemId = editingPersonal!!.id,
                        date = selectedDate,
                        title = title,
                        notes = notes,
                        startTime = start,
                        endTime = end,
                    )
                } else {
                    store.createPersonalItem(
                        date = selectedDate,
                        title = title,
                        notes = notes,
                        startTime = start,
                        endTime = end,
                    )
                }
                showingPersonalEditor = false
                editingPersonal = null
            },
            onDelete = editingPersonal?.let { item ->
                {
                    store.deletePersonalItem(itemId = item.id, date = selectedDate)
                    showingPersonalEditor = false
                    editingPersonal = null
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
    WhiteboardCard(
        modifier = Modifier.padding(horizontal = 14.dp),
        tint = ClinicalPalette.CardStrong,
        cornerRadius = 12.dp,
    ) {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .heightIn(min = 56.dp)
                .padding(horizontal = 4.dp, vertical = 8.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            IconButton(onClick = onPrevious, modifier = Modifier.size(48.dp)) {
                Icon(
                    Icons.Rounded.ChevronLeft,
                    contentDescription = "Previous",
                    tint = ClinicalPalette.Ink,
                )
            }
            Column(
                modifier = Modifier.weight(1f),
                horizontalAlignment = Alignment.CenterHorizontally,
            ) {
                Text(
                    title,
                    style = ClinicalTypography.headlineStrong,
                    color = ClinicalPalette.Ink,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                )
                Text(subtitle, style = ClinicalTypography.captionEmphasized, color = ClinicalPalette.Muted)
            }
            if (showToday) {
                ClinicalTodayChip(onClick = onToday)
            }
            IconButton(onClick = onNext, modifier = Modifier.size(48.dp)) {
                Icon(
                    Icons.Rounded.ChevronRight,
                    contentDescription = "Next",
                    tint = ClinicalPalette.Ink,
                )
            }
        }
    }
}

/** Day = card stack with fat color rails. */
@Composable
private fun DayDashboard(
    day: ScheduleDayUi,
    onCover: (CallAssignmentUi) -> Unit,
    onOpenPatients: () -> Unit,
    onAddPersonal: () -> Unit,
    onEditPersonal: (PersonalItemUi) -> Unit,
) {
    Column(
        modifier = Modifier.fillMaxWidth(),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        DashboardSection(
            title = "On call / Off",
            railColor = if (day.hasMyApprovedOff) ClinicalPalette.RailOff else ClinicalPalette.RailCall,
            tint = if (day.hasMyApprovedOff) ClinicalPalette.Mint else ClinicalPalette.CardStrong,
        ) {
            if (day.assignments.isEmpty()) {
                Text("No on-call coverage", style = ClinicalTypography.caption, color = ClinicalPalette.Muted)
            } else {
                day.assignments.forEach { assignment ->
                    Row(
                        modifier = Modifier
                            .fillMaxWidth()
                            .heightIn(min = 48.dp)
                            .clip(RoundedCornerShape(8.dp))
                            .clickable(enabled = assignment.rotationId != 0) { onCover(assignment) }
                            .padding(vertical = 6.dp, horizontal = 2.dp),
                        horizontalArrangement = Arrangement.SpaceBetween,
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        Column(modifier = Modifier.weight(1f)) {
                            Text(
                                assignment.group,
                                style = ClinicalTypography.rowTitleStrong,
                                color = ClinicalPalette.Ink,
                            )
                            Text(
                                assignment.locationShort,
                                style = ClinicalTypography.caption,
                                color = ClinicalPalette.Muted,
                            )
                        }
                        CoverageInitialsChip(assignment = assignment)
                    }
                }
            }
            if (day.off.isNotEmpty()) {
                FatStatusMark(
                    label = "OFF ${day.off.joinToString(" ")}",
                    fill = ClinicalPalette.Mint,
                    ink = ClinicalPalette.ScrubInk,
                )
            }
            if (day.requestedOff.isNotEmpty()) {
                Text(
                    "Requested: ${day.requestedOff.joinToString(" ")}",
                    style = ClinicalTypography.caption,
                    color = ClinicalPalette.Muted,
                )
            }
            if (day.hasMyApprovedOff) {
                FatStatusMark(
                    label = "YOU ARE OFF",
                    fill = ClinicalPalette.Scrub,
                    ink = ClinicalPalette.ScrubInk,
                )
            }
        }

        DashboardSection(
            title = "Clinic / OR Schedule",
            railColor = ClinicalPalette.RailClinic,
            tint = ClinicalPalette.CardStrong,
        ) {
            ClinicOrScheduleList(dayId = day.dateKey, items = day.mySchedule)
            if (day.mySchedule.isNotEmpty()) {
                TextButton(onClick = onOpenPatients) {
                    Text(
                        "Open Patients",
                        style = ClinicalTypography.rowTitleStrong,
                        color = ClinicalPalette.Teal,
                    )
                }
            }
        }

        DashboardSection(
            title = "Meetings",
            railColor = ClinicalPalette.RailMeeting,
            tint = ClinicalPalette.Lavender.copy(alpha = 0.45f).compositeOntoCard(),
        ) {
            if (day.meetings.isEmpty()) {
                Text("none", style = ClinicalTypography.caption, color = ClinicalPalette.Muted)
            } else {
                day.meetings.forEach { ScheduleItemRow(it, rail = ClinicalPalette.RailMeeting) }
            }
        }

        DashboardSection(
            title = "Personal",
            railColor = ClinicalPalette.RailPersonal,
            tint = ClinicalPalette.PorcelainChip,
        ) {
            if (day.personalItems.isEmpty()) {
                Text("none", style = ClinicalTypography.caption, color = ClinicalPalette.Muted)
            } else {
                day.personalItems.forEach { item ->
                    Row(
                        modifier = Modifier
                            .fillMaxWidth()
                            .heightIn(min = 44.dp)
                            .clip(RoundedCornerShape(8.dp))
                            .clickable { onEditPersonal(item) }
                            .padding(vertical = 4.dp),
                        horizontalArrangement = Arrangement.spacedBy(10.dp),
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        Box(
                            modifier = Modifier
                                .width(4.dp)
                                .height(28.dp)
                                .background(ClinicalPalette.RailPersonal, RoundedCornerShape(2.dp)),
                        )
                        Column(modifier = Modifier.weight(1f)) {
                            Text(
                                item.displayTitle,
                                style = ClinicalTypography.rowTitle,
                                color = ClinicalPalette.Ink,
                            )
                            if (item.notes.isNotBlank()) {
                                Text(
                                    item.notes,
                                    style = ClinicalTypography.captionEmphasized,
                                    color = ClinicalPalette.Muted,
                                )
                            }
                        }
                    }
                }
            }
            TextButton(onClick = onAddPersonal) {
                Icon(Icons.Rounded.Add, contentDescription = null, tint = ClinicalPalette.Teal)
                Text(
                    "Add personal",
                    style = ClinicalTypography.rowTitleStrong,
                    color = ClinicalPalette.Teal,
                )
            }
        }
    }
}

private fun Color.compositeOntoCard(): Color {
    val base = ClinicalPalette.Card
    val a = alpha.coerceIn(0f, 1f)
    return Color(
        red = red * a + base.red * (1f - a),
        green = green * a + base.green * (1f - a),
        blue = blue * a + base.blue * (1f - a),
        alpha = 1f,
    )
}

/** Week = vertical timeline with fat day markers + event bars. */
@Composable
private fun WeekTimeline(
    days: List<ScheduleDayUi>,
    selectedDate: LocalDate,
    onSelect: (LocalDate) -> Unit,
    onCover: (CallAssignmentUi) -> Unit,
) {
    WhiteboardCard(tint = ClinicalPalette.CardStrong, cornerRadius = 12.dp) {
        Column(
            modifier = Modifier.padding(vertical = 8.dp),
            verticalArrangement = Arrangement.spacedBy(0.dp),
        ) {
            days.forEachIndexed { index, day ->
                WeekTimelineRow(
                    day = day,
                    isSelected = day.date == selectedDate,
                    isToday = day.date == LocalDate.now(),
                    showConnector = index < days.lastIndex,
                    onSelect = { onSelect(day.date) },
                    onCover = onCover,
                )
            }
        }
    }
}

@Composable
private fun WeekTimelineRow(
    day: ScheduleDayUi,
    isSelected: Boolean,
    isToday: Boolean,
    showConnector: Boolean,
    onSelect: () -> Unit,
    onCover: (CallAssignmentUi) -> Unit,
) {
    val markerFill = when {
        day.hasMyApprovedOff -> ClinicalPalette.ScrubInk
        isSelected -> ClinicalPalette.Teal
        isToday -> ClinicalPalette.AuthAccent
        else -> ClinicalPalette.Stroke
    }
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .clickable(onClick = onSelect)
            .padding(horizontal = 12.dp),
    ) {
        Column(
            horizontalAlignment = Alignment.CenterHorizontally,
            modifier = Modifier.width(36.dp),
        ) {
            Box(
                modifier = Modifier
                    .size(if (isSelected) 18.dp else 12.dp)
                    .background(markerFill, RoundedCornerShape(4.dp)),
            )
            if (showConnector) {
                Box(
                    modifier = Modifier
                        .width(3.dp)
                        .height(8.dp)
                        .background(ClinicalPalette.Stroke.copy(alpha = 0.7f)),
                )
            }
        }
        Column(
            modifier = Modifier
                .weight(1f)
                .padding(bottom = if (showConnector) 10.dp else 4.dp)
                .then(
                    if (isSelected) {
                        Modifier
                            .background(ClinicalPalette.TealSoft.copy(alpha = 0.55f), RoundedCornerShape(10.dp))
                            .border(2.dp, ClinicalPalette.Teal, RoundedCornerShape(10.dp))
                    } else {
                        Modifier
                    },
                )
                .padding(horizontal = 10.dp, vertical = 10.dp),
            verticalArrangement = Arrangement.spacedBy(6.dp),
        ) {
            Text(
                "${day.weekdayShort.uppercase()}  ${day.date.format(DateTimeFormatter.ofPattern("MMM d"))}",
                style = if (isSelected) ClinicalTypography.headlineStrong else ClinicalTypography.rowTitleStrong,
                color = ClinicalPalette.Ink,
            )
            if (day.hasMyApprovedOff) {
                FatStatusMark(label = "OFF", fill = ClinicalPalette.Mint, ink = ClinicalPalette.ScrubInk)
            }
            day.assignments.forEach { assignment ->
                Row(
                    modifier = Modifier
                        .fillMaxWidth()
                        .heightIn(min = 40.dp)
                        .clip(RoundedCornerShape(6.dp))
                        .background(ClinicalPalette.SurfaceQuiet)
                        .clickable { onCover(assignment) }
                        .padding(horizontal = 8.dp, vertical = 6.dp),
                    horizontalArrangement = Arrangement.spacedBy(8.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Box(
                        modifier = Modifier
                            .width(5.dp)
                            .height(22.dp)
                            .background(ClinicalPalette.RailCall, RoundedCornerShape(2.dp)),
                    )
                    Text(
                        assignment.group,
                        style = ClinicalTypography.caption,
                        color = ClinicalPalette.Ink,
                        modifier = Modifier.weight(1f),
                        maxLines = 1,
                        overflow = TextOverflow.Ellipsis,
                    )
                    CoverageInitialsChip(assignment = assignment)
                }
            }
            if (day.mySchedule.isNotEmpty()) {
                TimelineBar(
                    color = ClinicalPalette.RailClinic,
                    text = day.mySchedule.joinToString(" · ") { it.title },
                )
            }
            if (day.hasBlockTime) {
                TimelineBar(color = ClinicalPalette.RailBlock, text = "Block")
            }
            if (day.hasMeeting) {
                TimelineBar(color = ClinicalPalette.RailMeeting, text = "Meeting")
            }
            if (day.off.isNotEmpty() && !day.hasMyApprovedOff) {
                Text(
                    "Off ${day.off.joinToString(" ")}",
                    style = ClinicalTypography.caption,
                    color = ClinicalPalette.Muted,
                )
            }
        }
    }
}

@Composable
private fun TimelineBar(color: Color, text: String) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .heightIn(min = 32.dp)
            .clip(RoundedCornerShape(6.dp))
            .background(color.copy(alpha = 0.18f))
            .padding(horizontal = 8.dp, vertical = 6.dp),
        horizontalArrangement = Arrangement.spacedBy(8.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Box(
            modifier = Modifier
                .width(6.dp)
                .height(18.dp)
                .background(color, RoundedCornerShape(2.dp)),
        )
        Text(
            text,
            style = ClinicalTypography.caption,
            color = ClinicalPalette.Ink,
            maxLines = 2,
            overflow = TextOverflow.Ellipsis,
        )
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
    val leading = (first.dayOfWeek.value + 6) % 7
    val daysInMonth = month.lengthOfMonth()
    val today = LocalDate.now()
    WhiteboardCard(tint = ClinicalPalette.CardStrong, cornerRadius = 12.dp) {
        Column(
            modifier = Modifier.padding(10.dp),
            verticalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            MonthDotLegend()

            Row(modifier = Modifier.fillMaxWidth()) {
                listOf("M", "T", "W", "T", "F", "S", "S").forEach { label ->
                    Text(
                        label,
                        modifier = Modifier.weight(1f),
                        textAlign = TextAlign.Center,
                        style = ClinicalTypography.badge,
                        color = ClinicalPalette.Muted,
                    )
                }
            }
            var dayNumber = 1
            repeat(6) { week ->
                if (dayNumber > daysInMonth) return@repeat
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.spacedBy(4.dp),
                ) {
                    repeat(7) { column ->
                        val cellIndex = week * 7 + column
                        if (cellIndex < leading || dayNumber > daysInMonth) {
                            Spacer(
                                modifier = Modifier
                                    .weight(1f)
                                    .heightIn(min = 64.dp),
                            )
                        } else {
                            val date = month.atDay(dayNumber)
                            MonthHeatmapCell(
                                date = date,
                                day = dayFor(date),
                                isSelected = date == selectedDate,
                                isToday = date == today,
                                onSelect = { onSelect(date) },
                                modifier = Modifier.weight(1f),
                            )
                            dayNumber += 1
                        }
                    }
                }
            }
        }
    }
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun MonthDotLegend() {
    Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
        Text(
            "YOUR MONTH",
            style = ClinicalTypography.sectionLabel,
            color = ClinicalPalette.Muted,
        )
        FlowRow(
            horizontalArrangement = Arrangement.spacedBy(10.dp),
            verticalArrangement = Arrangement.spacedBy(6.dp),
        ) {
            FatStatusMark(label = "OFF", fill = ClinicalPalette.Mint, ink = ClinicalPalette.ScrubInk, compact = true)
            MonthLegendBlock(color = ClinicalPalette.RailClinic, label = "Clinic/OR")
            MonthLegendBlock(color = ClinicalPalette.RailBlock, label = "Block")
            MonthLegendBlock(color = ClinicalPalette.RailMeeting, label = "Meeting")
        }
    }
}

@Composable
private fun MonthLegendBlock(color: Color, label: String) {
    Row(
        horizontalArrangement = Arrangement.spacedBy(5.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Box(
            modifier = Modifier
                .width(14.dp)
                .height(10.dp)
                .background(color, RoundedCornerShape(2.dp)),
        )
        Text(
            label,
            style = ClinicalTypography.captionEmphasized,
            color = ClinicalPalette.Ink.copy(alpha = 0.8f),
            maxLines = 1,
        )
    }
}

/** Month cell — high-contrast heatmap with fat color bars (not tiny letters). */
@Composable
private fun MonthHeatmapCell(
    date: LocalDate,
    day: ScheduleDayUi,
    isSelected: Boolean,
    isToday: Boolean,
    onSelect: () -> Unit,
    modifier: Modifier = Modifier,
) {
    val shape = RoundedCornerShape(8.dp)
    val background = when {
        day.hasMyApprovedOff -> ClinicalPalette.Mint
        isSelected -> ClinicalPalette.TealSoft
        isToday -> ClinicalPalette.TealSoft.copy(alpha = 0.55f)
        else -> ClinicalPalette.SurfaceQuiet
    }
    val borderColor = when {
        isSelected -> ClinicalPalette.Teal
        day.hasMyApprovedOff -> ClinicalPalette.ScrubInk
        isToday -> ClinicalPalette.Teal.copy(alpha = 0.55f)
        else -> ClinicalPalette.Stroke.copy(alpha = 0.45f)
    }
    val borderWidth = when {
        isSelected -> 2.5.dp
        day.hasMyApprovedOff || isToday -> 1.5.dp
        else -> 1.dp
    }

    Column(
        modifier = modifier
            .heightIn(min = if (isSelected) 72.dp else 64.dp)
            .clip(shape)
            .background(background)
            .border(borderWidth, borderColor, shape)
            .clickable(onClick = onSelect)
            .padding(horizontal = 3.dp, vertical = 5.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.spacedBy(3.dp),
    ) {
        Text(
            date.dayOfMonth.toString(),
            style = if (isSelected) {
                ClinicalTypography.dayNumberSelected
            } else {
                ClinicalTypography.dayNumber
            },
            color = when {
                day.hasMyApprovedOff -> ClinicalPalette.ScrubInk
                isSelected || isToday -> ClinicalPalette.Teal
                else -> ClinicalPalette.Ink
            },
            fontWeight = FontWeight.Bold,
        )
        if (day.hasMyApprovedOff) {
            Box(
                modifier = Modifier
                    .fillMaxWidth()
                    .height(12.dp)
                    .background(ClinicalPalette.ScrubInk, RoundedCornerShape(3.dp)),
                contentAlignment = Alignment.Center,
            ) {
                Text(
                    "OFF",
                    style = ClinicalTypography.badge,
                    color = ClinicalPalette.OnTeal,
                )
            }
        }
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .height(8.dp),
            horizontalArrangement = Arrangement.spacedBy(2.dp),
        ) {
            if (day.hasClinicOr) {
                Box(
                    modifier = Modifier
                        .weight(1f)
                        .fillMaxHeight()
                        .background(ClinicalPalette.RailClinic, RoundedCornerShape(2.dp)),
                )
            }
            if (day.hasBlockTime) {
                Box(
                    modifier = Modifier
                        .weight(1f)
                        .fillMaxHeight()
                        .background(ClinicalPalette.RailBlock, RoundedCornerShape(2.dp)),
                )
            }
            if (day.hasMeeting) {
                Box(
                    modifier = Modifier
                        .weight(1f)
                        .fillMaxHeight()
                        .background(ClinicalPalette.RailMeeting, RoundedCornerShape(2.dp)),
                )
            }
        }
    }
}

@Composable
private fun ScheduleItemRow(item: ScheduleItemUi, rail: Color = ClinicalPalette.RailClinic) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(8.dp))
            .background(ClinicalPalette.SurfaceQuiet)
            .padding(10.dp),
        horizontalArrangement = Arrangement.spacedBy(10.dp),
    ) {
        Box(
            modifier = Modifier
                .width(5.dp)
                .heightIn(min = 36.dp)
                .background(rail, RoundedCornerShape(2.dp)),
        )
        Column(modifier = Modifier.weight(1f)) {
            if (item.period.isNotBlank()) {
                Text(
                    item.period,
                    style = ClinicalTypography.captionEmphasized,
                    color = ClinicalPalette.Teal,
                )
            }
            Text(item.title, style = ClinicalTypography.rowTitleStrong, color = ClinicalPalette.Ink)
            if (item.subtitle.isNotBlank()) {
                Text(item.subtitle, style = ClinicalTypography.caption, color = ClinicalPalette.Muted)
            }
            if (item.timeRange.isNotBlank()) {
                Text(item.timeRange, style = ClinicalTypography.caption, color = ClinicalPalette.Muted)
            }
        }
    }
}

@Composable
private fun FatStatusMark(
    label: String,
    fill: Color,
    ink: Color,
    compact: Boolean = false,
) {
    Text(
        label,
        style = ClinicalTypography.badge,
        color = ink,
        fontWeight = FontWeight.Bold,
        modifier = Modifier
            .clip(RoundedCornerShape(6.dp))
            .background(fill)
            .border(1.5.dp, ink.copy(alpha = 0.35f), RoundedCornerShape(6.dp))
            .padding(
                horizontal = if (compact) 8.dp else 10.dp,
                vertical = if (compact) 4.dp else 6.dp,
            ),
    )
}

@Composable
private fun WarningBanner(message: String) {
    WhiteboardCard(tint = ClinicalPalette.Amber, cornerRadius = 12.dp) {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(14.dp),
            horizontalArrangement = Arrangement.spacedBy(10.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Box(
                modifier = Modifier
                    .width(6.dp)
                    .height(36.dp)
                    .background(ClinicalPalette.Urgency, RoundedCornerShape(3.dp)),
            )
            Text(
                message,
                style = ClinicalTypography.caption,
                color = ClinicalPalette.Ink,
                modifier = Modifier.weight(1f),
            )
        }
    }
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
            val start = weekDays.firstOrNull()?.date
                ?: selectedDate.with(TemporalAdjusters.previousOrSame(DayOfWeek.MONDAY))
            val end = weekDays.lastOrNull()?.date ?: start.plusDays(6)
            "${start.format(monthDay)} – ${end.format(monthDay)}"
        }
        ScheduleScope.Month -> {
            selectedDate.month.getDisplayName(TextStyle.FULL, Locale.US) + " ${selectedDate.year}"
        }
    }
}
