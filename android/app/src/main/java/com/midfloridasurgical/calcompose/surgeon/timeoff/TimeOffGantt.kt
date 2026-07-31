package com.midfloridasurgical.calcompose.surgeon.timeoff

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.offset
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.midfloridasurgical.calcompose.data.models.NativeSurgeon
import com.midfloridasurgical.calcompose.data.models.ScheduleDayUi
import com.midfloridasurgical.calcompose.ui.theme.ClinicalPalette
import com.midfloridasurgical.calcompose.ui.theme.ClinicalTypography
import java.time.DayOfWeek
import java.time.LocalDate
import java.time.YearMonth
import kotlin.math.max

enum class TimeOffBarStatus { Approved, Pending }

data class TimeOffGanttBar(
    val id: String,
    val startDay: Int,
    val endDay: Int,
    val status: TimeOffBarStatus,
) {
    val spanDays: Int get() = endDay - startDay + 1
}

data class TimeOffGanttRow(
    val id: String,
    val initials: String,
    val name: String,
    val bars: List<TimeOffGanttBar>,
) {
    val hasBars: Boolean get() = bars.isNotEmpty()
}

data class TimeOffGanttModel(
    val daysInMonth: Int,
    val dayNumbers: List<Int>,
    val rows: List<TimeOffGanttRow>,
) {
    companion object {
        fun build(
            month: YearMonth,
            days: List<ScheduleDayUi>,
            surgeons: List<NativeSurgeon>,
        ): TimeOffGanttModel {
            val daysInMonth = month.lengthOfMonth()
            val dayNumbers = (1..daysInMonth).toList()
            val dayByNumber = days
                .filter { YearMonth.from(it.date) == month }
                .associateBy { it.date.dayOfMonth }

            // status[initials][day] = approved | pending (approved wins if both)
            val statusBySurgeon = mutableMapOf<String, MutableMap<Int, TimeOffBarStatus>>()
            for (dayNum in dayNumbers) {
                val day = dayByNumber[dayNum] ?: continue
                for (initial in day.off) {
                    statusBySurgeon.getOrPut(initial) { mutableMapOf() }[dayNum] =
                        TimeOffBarStatus.Approved
                }
                for (initial in day.requestedOff) {
                    val map = statusBySurgeon.getOrPut(initial) { mutableMapOf() }
                    if (map[dayNum] == null) {
                        map[dayNum] = TimeOffBarStatus.Pending
                    }
                }
            }

            // Portal Who’s Out shows every roster surgeon (empty rows dimmed).
            val surgeonByInitials = linkedMapOf<String, NativeSurgeon>()
            for (surgeon in surgeons) {
                val key = surgeon.initials.trim()
                if (key.isEmpty()) continue
                if (key !in surgeonByInitials) surgeonByInitials[key] = surgeon
            }
            val orderedInitials = mutableListOf<String>()
            val seen = mutableSetOf<String>()
            for (surgeon in surgeons) {
                val key = surgeon.initials.trim()
                if (key.isEmpty()) continue
                if (seen.add(key)) orderedInitials.add(key)
            }
            for (key in statusBySurgeon.keys.sorted()) {
                if (seen.add(key)) orderedInitials.add(key)
            }

            val rows = orderedInitials.map { initials ->
                val map = statusBySurgeon[initials].orEmpty()
                TimeOffGanttRow(
                    id = initials,
                    initials = initials,
                    name = surgeonByInitials[initials]?.name ?: initials,
                    bars = coalesceBars(map, daysInMonth),
                )
            }

            return TimeOffGanttModel(
                daysInMonth = daysInMonth,
                dayNumbers = dayNumbers,
                rows = rows,
            )
        }

        private fun coalesceBars(
            dayStatuses: Map<Int, TimeOffBarStatus>,
            daysInMonth: Int,
        ): List<TimeOffGanttBar> {
            val bars = mutableListOf<TimeOffGanttBar>()
            var cursor = 1
            while (cursor <= daysInMonth) {
                val status = dayStatuses[cursor]
                if (status == null) {
                    cursor += 1
                    continue
                }
                var end = cursor
                while (end + 1 <= daysInMonth && dayStatuses[end + 1] == status) {
                    end += 1
                }
                bars.add(
                    TimeOffGanttBar(
                        id = "${status.name.lowercase()}-$cursor-$end",
                        startDay = cursor,
                        endDay = end,
                        status = status,
                    ),
                )
                cursor = end + 1
            }
            return bars
        }
    }
}

private val DayWidth = 22.dp
private val LabelWidth = 44.dp
private val RowHeight = 28.dp
private val HeaderHeight = 22.dp

@Composable
fun TimeOffGanttView(
    model: TimeOffGanttModel,
    selectedMonth: YearMonth,
) {
    if (model.daysInMonth == 0) {
        Text("Could not load month.", color = ClinicalPalette.Muted, style = ClinicalTypography.caption)
        return
    }
    if (model.rows.isEmpty()) {
        Text(
            "No requested or approved time off this month.",
            color = ClinicalPalette.Muted,
            style = ClinicalTypography.caption,
            modifier = Modifier.padding(vertical = 6.dp),
        )
        return
    }

    val today = LocalDate.now()
    val todayDayNumber = remember(selectedMonth) {
        if (YearMonth.from(today) == selectedMonth) today.dayOfMonth else null
    }
    val hScroll = rememberScrollState()
    val density = LocalDensity.current
    val dayWidthPx = with(density) { DayWidth.toPx() }

    // Pin today at leading edge when month contains today; else day 1.
    LaunchedEffect(selectedMonth, model.daysInMonth) {
        val targetDay = todayDayNumber ?: 1
        val offset = max(0, ((targetDay - 1) * dayWidthPx).toInt())
        hScroll.scrollTo(offset)
    }

    val gridHeight = HeaderHeight + RowHeight * model.rows.size
    val rowRule = ClinicalPalette.Stroke.copy(alpha = 0.85f)

    Column(
        modifier = Modifier.fillMaxWidth(),
        verticalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
            LegendSwatch(ClinicalPalette.Mint, "Approved")
            LegendSwatch(ClinicalPalette.Amber, "Pending")
        }

        Row(
            modifier = Modifier
                .fillMaxWidth()
                .clip(RoundedCornerShape(8.dp)),
        ) {
            // Sticky name column
            Column(
                modifier = Modifier
                    .background(ClinicalPalette.CardStrong.copy(alpha = 0.92f))
                    .padding(end = 6.dp),
            ) {
                Box(
                    modifier = Modifier
                        .width(LabelWidth)
                        .height(HeaderHeight),
                    contentAlignment = Alignment.CenterStart,
                ) {
                    Text(
                        "MD",
                        style = ClinicalTypography.badge,
                        color = ClinicalPalette.Muted,
                    )
                }
                Box(
                    Modifier
                        .width(LabelWidth)
                        .height(0.5.dp)
                        .background(rowRule),
                )
                model.rows.forEach { row ->
                    Box(
                        modifier = Modifier
                            .width(LabelWidth)
                            .height(RowHeight),
                        contentAlignment = Alignment.CenterStart,
                    ) {
                        Text(
                            row.initials,
                            style = ClinicalTypography.monoChip,
                            color = ClinicalPalette.Ink.copy(alpha = if (row.hasBars) 1f else 0.55f),
                            maxLines = 1,
                            overflow = TextOverflow.Ellipsis,
                        )
                    }
                    Box(
                        Modifier
                            .width(LabelWidth)
                            .height(0.5.dp)
                            .background(rowRule),
                    )
                }
            }

            Box {
                Column(
                    modifier = Modifier.horizontalScroll(hScroll),
                ) {
                    // Day header
                    Row {
                        model.dayNumbers.forEach { day ->
                            val isToday = todayDayNumber == day
                            Box(
                                modifier = Modifier
                                    .width(DayWidth)
                                    .height(HeaderHeight)
                                    .background(
                                        if (isToday) {
                                            ClinicalPalette.TealSoft.copy(alpha = 0.55f)
                                        } else {
                                            ClinicalPalette.Transparent
                                        },
                                    ),
                                contentAlignment = Alignment.Center,
                            ) {
                                Text(
                                    "$day",
                                    style = ClinicalTypography.badge,
                                    color = if (isToday) ClinicalPalette.Teal else ClinicalPalette.Muted,
                                )
                            }
                        }
                    }
                    Box(
                        Modifier
                            .width(DayWidth * model.daysInMonth)
                            .height(0.5.dp)
                            .background(rowRule),
                    )

                    model.rows.forEach { row ->
                        TimelineRow(
                            row = row,
                            daysInMonth = model.daysInMonth,
                            dayNumbers = model.dayNumbers,
                            selectedMonth = selectedMonth,
                            todayDayNumber = todayDayNumber,
                            rowRule = rowRule,
                            dimmed = !row.hasBars,
                        )
                    }
                }

                // Today vertical line
                todayDayNumber?.let { todayDay ->
                    Box(
                        modifier = Modifier
                            .offset(x = DayWidth * (todayDay - 1) + DayWidth / 2 - 1.dp)
                            .width(2.dp)
                            .height(gridHeight)
                            .background(ClinicalPalette.Teal),
                    )
                }
            }
        }
    }
}

@Composable
private fun TimelineRow(
    row: TimeOffGanttRow,
    daysInMonth: Int,
    dayNumbers: List<Int>,
    selectedMonth: YearMonth,
    todayDayNumber: Int?,
    rowRule: Color,
    dimmed: Boolean,
) {
    Box(
        modifier = Modifier
            .width(DayWidth * daysInMonth)
            .height(RowHeight)
            .alpha(if (dimmed) 0.55f else 1f),
    ) {
        Row {
            dayNumbers.forEach { day ->
                Box(
                    modifier = Modifier
                        .width(DayWidth)
                        .height(RowHeight)
                        .background(dayBackground(day, selectedMonth, todayDayNumber)),
                )
            }
        }
        row.bars.forEach { bar ->
            val x = DayWidth * (bar.startDay - 1) + 1.dp
            val w = DayWidth * bar.spanDays - 2.dp
            Box(
                modifier = Modifier
                    .offset(x = x, y = 4.dp)
                    .width(maxOf(w, 4.dp))
                    .height(RowHeight - 8.dp)
                    .background(
                        if (bar.status == TimeOffBarStatus.Approved) {
                            ClinicalPalette.Mint
                        } else {
                            ClinicalPalette.Amber
                        },
                        RoundedCornerShape(4.dp),
                    )
                    .border(
                        0.5.dp,
                        ClinicalPalette.Ink.copy(alpha = 0.08f),
                        RoundedCornerShape(4.dp),
                    ),
                contentAlignment = Alignment.Center,
            ) {
                Text(
                    if (bar.spanDays > 1) "${bar.startDay}–${bar.endDay}" else "${bar.startDay}",
                    style = ClinicalTypography.badge,
                    color = ClinicalPalette.Ink.copy(alpha = 0.85f),
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                )
            }
        }
        Box(
            Modifier
                .align(Alignment.BottomStart)
                .width(DayWidth * daysInMonth)
                .height(0.5.dp)
                .background(rowRule),
        )
    }
}

private fun dayBackground(
    day: Int,
    selectedMonth: YearMonth,
    todayDayNumber: Int?,
): Color {
    if (todayDayNumber == day) return ClinicalPalette.TealSoft.copy(alpha = 0.28f)
    val date = runCatching { selectedMonth.atDay(day) }.getOrNull() ?: return ClinicalPalette.Transparent
    val weekend = date.dayOfWeek == DayOfWeek.SATURDAY || date.dayOfWeek == DayOfWeek.SUNDAY
    return if (weekend) ClinicalPalette.Ink.copy(alpha = 0.03f) else ClinicalPalette.Transparent
}

@Composable
private fun LegendSwatch(color: Color, label: String) {
    Row(
        horizontalArrangement = Arrangement.spacedBy(4.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Box(
            modifier = Modifier
                .width(12.dp)
                .height(8.dp)
                .background(color, RoundedCornerShape(3.dp)),
        )
        Text(
            label,
            style = ClinicalTypography.captionEmphasized,
            color = ClinicalPalette.Muted,
        )
    }
}
