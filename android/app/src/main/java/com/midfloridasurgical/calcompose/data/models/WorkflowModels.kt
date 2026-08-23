package com.midfloridasurgical.calcompose.data.models

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

@Serializable
data class TimeOffSubmitRequest(
    @SerialName("start_date") val startDate: String,
    @SerialName("end_date") val endDate: String,
    val reason: String,
    val notes: String = "",
    @SerialName("is_full_day") val isFullDay: Boolean = true,
    val start: String? = null,
    val end: String? = null,
    val segments: List<TimeOffSubmitSegment> = emptyList(),
)

@Serializable
data class TimeOffSubmitSegment(
    val date: String,
    val isFullDay: Boolean = true,
    val start: String = "07:00",
    val end: String = "17:00",
)

@Serializable
data class NativeRequestOffResponse(
    val ok: Boolean = false,
    val warnings: List<String> = emptyList(),
    val emailed: Boolean = false,
)

@Serializable
data class CallCoverageRequest(
    @SerialName("rotation_id") val rotationId: Int,
    @SerialName("covering_surgeon_id") val coveringSurgeonId: Int,
    val notes: String = "",
)

@Serializable
data class NativeCallCoverageResponse(
    val ok: Boolean = false,
    val assignment: NativeCallAssignment,
)

@Serializable
data class DayItemWritePayload(
    val date: String,
    val title: String,
    val notes: String = "",
    @SerialName("start_time") val startTime: String? = null,
    @SerialName("end_time") val endTime: String? = null,
)

@Serializable
data class DayItemPatchPayload(
    val title: String,
    val notes: String = "",
    @SerialName("start_time") val startTime: String? = null,
    @SerialName("end_time") val endTime: String? = null,
)

@Serializable
data class NativePatientScheduleResponse(
    val appointments: List<NativePatientAppointment> = emptyList(),
    val warning: String? = null,
)

@Serializable
data class NativePatientAppointment(
    val id: String? = null,
    val date: String,
    val start: String = "",
    val end: String = "",
    val surgeonInitials: String = "",
    val surgeonName: String = "",
    val patientName: String = "",
    val mrn: String? = null,
    val appointmentType: String = "",
    val status: String = "",
    val reason: String = "",
    val serviceSite: String = "",
    val room: String = "",
)
