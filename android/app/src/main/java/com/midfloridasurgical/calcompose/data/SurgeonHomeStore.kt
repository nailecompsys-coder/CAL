package com.midfloridasurgical.calcompose.data

import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import com.midfloridasurgical.calcompose.data.models.NativeDayOffRequest
import com.midfloridasurgical.calcompose.data.models.NativeHomeResponse
import com.midfloridasurgical.calcompose.data.models.NativeSurgeon
import com.midfloridasurgical.calcompose.data.models.ScheduleDayUi
import com.midfloridasurgical.calcompose.data.models.emptyScheduleDay
import com.midfloridasurgical.calcompose.data.models.toUi
import java.time.LocalDate
import java.time.temporal.TemporalAdjusters
import java.time.DayOfWeek

class SurgeonHomeStore(
    private val apiClient: CalApiClient,
    private val token: String,
    private val deviceToken: String,
) {
    var isLoading by mutableStateOf(false)
        private set
    var warningMessage by mutableStateOf<String?>(null)
    var currentSurgeon by mutableStateOf<NativeSurgeon?>(null)
        private set
    var surgeons by mutableStateOf<List<NativeSurgeon>>(emptyList())
        private set
    var days by mutableStateOf<List<ScheduleDayUi>>(emptyList())
        private set
    var requests by mutableStateOf<List<NativeDayOffRequest>>(emptyList())
        private set

    private val daysByDate: Map<LocalDate, ScheduleDayUi>
        get() = days.associateBy { it.date }

    suspend fun refresh(containing: LocalDate = LocalDate.now(), daysAhead: Long = 45) {
        isLoading = true
        warningMessage = null
        runCatching {
            apiClient.fetchHome(
                token = token,
                deviceToken = deviceToken,
                start = containing.minusDays(7),
                end = containing.plusDays(daysAhead),
            )
        }.onSuccess { applyHome(it) }
            .onFailure { warningMessage = it.message ?: "Could not load CAL schedule." }
        isLoading = false
    }

    suspend fun submitTimeOff(start: LocalDate, end: LocalDate, reason: String): List<String> {
        val response = apiClient.submitRequestOff(
            token = token,
            deviceToken = deviceToken,
            startDate = start,
            endDate = end,
            reason = reason,
        )
        refresh(containing = start)
        return response.warnings
    }

    suspend fun submitCallCoverage(rotationId: Int, coveringSurgeonId: Int) {
        apiClient.submitCallCoverage(
            token = token,
            deviceToken = deviceToken,
            rotationId = rotationId,
            coveringSurgeonId = coveringSurgeonId,
        )
        refresh()
    }

    fun day(forDate: LocalDate): ScheduleDayUi =
        daysByDate[forDate] ?: emptyScheduleDay(forDate)

    fun week(containing: LocalDate): List<ScheduleDayUi> {
        val start = containing.with(TemporalAdjusters.previousOrSame(DayOfWeek.SUNDAY))
        return (0..6).map { day(start.plusDays(it.toLong())) }
    }

    fun eligibleCoveringSurgeons(originalSurgeonId: Int?, fallbackStaffType: String?): List<NativeSurgeon> {
        val targetStaffType = originalSurgeonId
            ?.let { id -> surgeons.firstOrNull { it.id == id }?.staffType }
            ?: fallbackStaffType
            ?: currentSurgeon?.staffType
        return surgeons
            .filter { targetStaffType == null || it.staffType == targetStaffType }
            .sortedWith(compareBy({ it.sortOrder ?: Int.MAX_VALUE }, { it.initials }))
    }

    private fun applyHome(home: NativeHomeResponse) {
        currentSurgeon = home.surgeon
        surgeons = home.surgeons
        days = home.days.map { it.toUi() }.sortedBy { it.date }
        requests = home.requests.sortedWith(compareBy({ it.startDate }, { it.id }))
    }
}
