package com.midfloridasurgical.calcompose.data.models

import java.time.LocalDate
import java.time.format.DateTimeFormatter
import java.time.format.TextStyle
import java.util.Locale

private val isoDate: DateTimeFormatter = DateTimeFormatter.ISO_LOCAL_DATE

data class ScheduleDayUi(
    val date: LocalDate,
    val assignments: List<CallAssignmentUi>,
    val off: List<String>,
    val requestedOff: List<String>,
    val mySchedule: List<ScheduleItemUi>,
    val meetings: List<ScheduleItemUi>,
    val personalItems: List<String>,
    val hasMyApprovedOff: Boolean,
) {
    val dateKey: String get() = date.format(isoDate)
    val weekdayShort: String
        get() = date.dayOfWeek.getDisplayName(TextStyle.SHORT, Locale.US)
    val weekdayFull: String
        get() = date.dayOfWeek.getDisplayName(TextStyle.FULL, Locale.US)
}

data class CallAssignmentUi(
    val rotationId: Int,
    val group: String,
    val displayInitials: String,
    val originalInitials: String,
    val originalSurgeonId: Int?,
    val surgeonId: Int?,
    val coveringInitials: String?,
    val coveringSurgeonId: Int?,
    val isCovered: Boolean,
)

data class ScheduleItemUi(
    val id: String,
    val period: String,
    val title: String,
    val subtitle: String,
    val timeRange: String,
    val kind: String,
)

fun NativeDayResponse.toUi(): ScheduleDayUi {
    val parsed = runCatching { LocalDate.parse(date, isoDate) }.getOrElse { LocalDate.now() }
    val scheduleItems = items.mapNotNull { it.toDoctorScheduleItem(date) }
    val meetingItems = items.mapNotNull { it.toMeetingItem(date) }
    val personal = items
        .filter { it.type == "personal" }
        .map { listOfNotNull(it.title.takeIf { t -> t.isNotBlank() }, it.start).joinToString(" ") }
        .filter { it.isNotBlank() }

    return ScheduleDayUi(
        date = parsed,
        assignments = callAssignments.map { it.toUi() },
        off = offSurgeons.map { it.initials },
        requestedOff = requestedOffSurgeons.map { it.initials },
        mySchedule = scheduleItems,
        meetings = meetingItems,
        personalItems = personal,
        hasMyApprovedOff = items.any { it.type == "dayoff" },
    )
}

fun NativeCallAssignment.toUi(): CallAssignmentUi {
    val fallbackInitials = initials
        ?: surgeon.split(" ").mapNotNull { it.firstOrNull()?.uppercaseChar() }.take(2).joinToString("")
            .ifBlank { surgeon }
    return CallAssignmentUi(
        rotationId = rotationId,
        group = group,
        displayInitials = coveringInitials ?: fallbackInitials,
        originalInitials = originalInitials ?: fallbackInitials,
        originalSurgeonId = originalSurgeonId ?: surgeonId,
        surgeonId = surgeonId,
        coveringInitials = coveringInitials,
        coveringSurgeonId = coveringSurgeonId,
        isCovered = isCovered == true,
    )
}

private fun NativeScheduleItem.toDoctorScheduleItem(dateKey: String): ScheduleItemUi? {
    if (type in setOf("personal", "meeting", "oncall", "dayoff") || allDay == true) return null
    return ScheduleItemUi(
        id = id ?: "$dateKey-${rawId ?: 0}-$title",
        period = periodLabel(),
        title = displayTitle(),
        subtitle = listOfNotNull(location, room, subtitle).filter { it.isNotBlank() }.joinToString(" · "),
        timeRange = timeRange(),
        kind = type,
    )
}

private fun NativeScheduleItem.toMeetingItem(dateKey: String): ScheduleItemUi? {
    if (type != "meeting") return null
    return ScheduleItemUi(
        id = id ?: "$dateKey-meeting-${rawId ?: 0}-$title",
        period = "MTG",
        title = title.ifBlank { "Meeting" },
        subtitle = listOfNotNull(location, room, subtitle, notes).filter { it.isNotBlank() }.joinToString(" · "),
        timeRange = timeRange(),
        kind = "meeting",
    )
}

private fun NativeScheduleItem.displayTitle(): String = when (type) {
    "clinic" -> title.ifBlank { "Clinic" }
    "surgery" -> title.ifBlank { "Hospital" }
    "block_or" -> title.ifBlank { "Block OR" }
    else -> title
}

private fun NativeScheduleItem.periodLabel(): String {
    val session = subtitle?.uppercase()
    if (type == "clinic" && session in setOf("AM", "PM", "FULL")) return session!!
    val startTime = start ?: return "DAY"
    return if (startTime < "12:00") "AM" else "PM"
}

private fun NativeScheduleItem.timeRange(): String {
    val startText = displayTime(start)
    val endText = displayTime(end)
    if (startText.isEmpty()) return ""
    if (endText.isEmpty()) return startText
    return "$startText - $endText"
}

private fun displayTime(value: String?): String {
    if (value.isNullOrBlank()) return ""
    val parts = value.split(":")
    val hour = parts.firstOrNull()?.toIntOrNull() ?: return value
    val minute = parts.getOrNull(1) ?: "00"
    return "%02d:%s".format(hour, minute)
}

fun emptyScheduleDay(date: LocalDate): ScheduleDayUi = ScheduleDayUi(
    date = date,
    assignments = emptyList(),
    off = emptyList(),
    requestedOff = emptyList(),
    mySchedule = emptyList(),
    meetings = emptyList(),
    personalItems = emptyList(),
    hasMyApprovedOff = false,
)
