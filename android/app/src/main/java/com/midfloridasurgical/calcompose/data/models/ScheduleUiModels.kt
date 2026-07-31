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
    val personalItems: List<PersonalItemUi>,
    val hasMyApprovedOff: Boolean,
    val hasClinicOr: Boolean = false,
    val hasBlockTime: Boolean = false,
    val hasMeeting: Boolean = false,
) {
    val dateKey: String get() = date.format(isoDate)
    val weekdayShort: String
        get() = date.dayOfWeek.getDisplayName(TextStyle.SHORT, Locale.US)
    val weekdayFull: String
        get() = date.dayOfWeek.getDisplayName(TextStyle.FULL, Locale.US)
}

data class CallAssignmentUi(
    val rotationId: Int,
    val coverageId: Int?,
    val group: String,
    val locationShort: String,
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
    val location: String = "",
    val room: String = "",
    val procedure: String = "",
    val notes: String = "",
    val start: String = "",
    val end: String = "",
) {
    val isBlockOr: Boolean get() = kind == "block_or"
    val isClinicOrSurgery: Boolean get() = kind == "clinic" || kind == "surgery"
}

/** Mirrors iOS `PersonalCalendarItem` — needs `rawId` for CRUD. */
data class PersonalItemUi(
    val id: Int,
    val title: String,
    val notes: String,
    val start: String,
    val end: String,
) {
    val displayTitle: String
        get() {
            val time = displayTime12(start)
            return if (time.isEmpty()) title else "$title $time"
        }

    val timeRangeLabel: String
        get() {
            val startText = displayTime12(start)
            val endText = displayTime12(end)
            if (startText.isEmpty()) return ""
            if (endText.isEmpty()) return startText
            return "$startText – $endText"
        }
}

object PersonalItemPresets {
    const val OTHER = "Other"
    val titles = listOf(
        "Personal appointment",
        "Doctor appointment",
        "Dental",
        "Family",
        "Kids / school",
        "Travel",
        "Errand",
        OTHER,
    )
}

fun NativeDayResponse.toUi(): ScheduleDayUi {
    val parsed = runCatching { LocalDate.parse(date, isoDate) }.getOrElse { LocalDate.now() }
    val scheduleItems = items.mapNotNull { it.toDoctorScheduleItem(date) }
    val meetingItems = items.mapNotNull { it.toMeetingItem(date) }
    val personal = items.mapNotNull { it.toPersonalItem() }

    return ScheduleDayUi(
        date = parsed,
        assignments = callAssignments.map { it.toUi() },
        off = offSurgeons.map { it.initials },
        requestedOff = requestedOffSurgeons.map { it.initials },
        mySchedule = scheduleItems,
        meetings = meetingItems,
        personalItems = personal,
        hasMyApprovedOff = items.any { it.type == "dayoff" },
        hasClinicOr = items.any { it.type == "clinic" || it.type == "surgery" },
        hasBlockTime = items.any { it.type == "block_or" },
        hasMeeting = items.any { it.type == "meeting" },
    )
}

fun NativeCallAssignment.toUi(): CallAssignmentUi {
    val fallbackInitials = initials
        ?: surgeon.split(" ").mapNotNull { it.firstOrNull()?.uppercaseChar() }.take(2).joinToString("")
            .ifBlank { surgeon }
    return CallAssignmentUi(
        rotationId = rotationId,
        coverageId = coverageId,
        group = group,
        locationShort = shortGroupName(group),
        displayInitials = coveringInitials ?: fallbackInitials,
        originalInitials = originalInitials ?: fallbackInitials,
        originalSurgeonId = originalSurgeonId ?: surgeonId,
        surgeonId = surgeonId,
        coveringInitials = coveringInitials,
        coveringSurgeonId = coveringSurgeonId,
        isCovered = isCovered == true,
    )
}

private fun shortGroupName(group: String): String {
    val upper = group.uppercase(Locale.US)
    if (upper.contains("WINTER") || upper.contains("APOPKA") || upper.contains("MINNEOLA")) {
        return "WG / A / Minneola"
    }
    if (upper.contains("ALTAMONTE")) {
        return "Altamonte Hosp"
    }
    return group
}

private fun NativeScheduleItem.toPersonalItem(): PersonalItemUi? {
    if (type != "personal") return null
    val itemId = rawId ?: return null
    return PersonalItemUi(
        id = itemId,
        title = title,
        notes = (notes ?: subtitle).orEmpty().trim(),
        start = start.orEmpty(),
        end = end.orEmpty(),
    )
}

private fun NativeScheduleItem.toDoctorScheduleItem(dateKey: String): ScheduleItemUi? {
    if (type in setOf("personal", "meeting", "oncall", "dayoff") || allDay == true) return null
    val procedure = (subtitle ?: "").trim()
    val loc = (location ?: "").trim()
    val roomValue = (room ?: "").trim()
    return ScheduleItemUi(
        id = id ?: "$dateKey-${rawId ?: 0}-$title",
        period = periodLabel(),
        title = displayTitle(),
        subtitle = listOf(loc, roomValue, procedure).filter { it.isNotBlank() }.joinToString(" · "),
        timeRange = timeRange(),
        kind = type,
        location = loc,
        room = roomValue,
        procedure = procedure,
        notes = (notes ?: "").trim(),
        start = start.orEmpty(),
        end = end.orEmpty(),
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
        location = (location ?: "").trim(),
        room = (room ?: "").trim(),
        procedure = (subtitle ?: "").trim(),
        notes = (notes ?: "").trim(),
        start = start.orEmpty(),
        end = end.orEmpty(),
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

private fun displayTime12(value: String): String {
    if (value.isBlank()) return ""
    val parts = value.split(":")
    val hour24 = parts.firstOrNull()?.toIntOrNull() ?: return value
    val minute = parts.getOrNull(1) ?: "00"
    val hour12 = ((hour24 + 11) % 12) + 1
    val suffix = if (hour24 >= 12) "PM" else "AM"
    return "$hour12:$minute $suffix"
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
