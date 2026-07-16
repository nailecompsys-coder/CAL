package com.midfloridasurgical.calcompose.data.models

import kotlinx.serialization.Serializable

@Serializable
data class NativeHomeResponse(
    val surgeon: NativeSurgeon? = null,
    val days: List<NativeDayResponse> = emptyList(),
    val requests: List<NativeDayOffRequest> = emptyList(),
    val surgeons: List<NativeSurgeon> = emptyList(),
    val alerts: NativeAlertSummary? = null,
)

@Serializable
data class NativeSurgeon(
    val id: Int,
    val name: String,
    val initials: String = "",
    val staffType: String = "physician",
    val sortOrder: Int? = null,
)

@Serializable
data class NativeAlertSummary(
    val unreadCount: Int = 0,
    val recent: List<NativeScheduleAlert> = emptyList(),
)

@Serializable
data class NativeScheduleAlert(
    val id: Int,
    val title: String,
    val body: String,
    val kind: String = "",
    val isRead: Boolean = false,
    val createdAt: String = "",
)

@Serializable
data class NativeDayResponse(
    val date: String,
    val dayName: String? = null,
    val dayShort: String? = null,
    val dayFull: String? = null,
    val items: List<NativeScheduleItem> = emptyList(),
    val offSurgeons: List<NativeOffSurgeon> = emptyList(),
    val requestedOffSurgeons: List<NativeOffSurgeon> = emptyList(),
    val callAssignments: List<NativeCallAssignment> = emptyList(),
)

@Serializable
data class NativeScheduleItem(
    val id: String? = null,
    val rawId: Int? = null,
    val type: String,
    val title: String = "",
    val subtitle: String? = null,
    val start: String? = null,
    val end: String? = null,
    val allDay: Boolean? = null,
    val location: String? = null,
    val room: String? = null,
    val notes: String? = null,
)

@Serializable
data class NativeOffSurgeon(val initials: String)

@Serializable
data class NativeCallAssignment(
    val rotationId: Int,
    val surgeonId: Int? = null,
    val group: String = "Call",
    val surgeon: String = "",
    val initials: String? = null,
    val originalInitials: String? = null,
    val originalSurgeonId: Int? = null,
    val coveringInitials: String? = null,
    val coveringSurgeonId: Int? = null,
    val isCovered: Boolean? = null,
)

@Serializable
data class NativeDayOffRequest(
    val id: Int,
    val surgeonInitials: String? = null,
    val startDate: String,
    val endDate: String,
    val reason: String = "",
    val status: String = "",
)
