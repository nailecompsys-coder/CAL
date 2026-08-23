package com.midfloridasurgical.calcompose.data

import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import com.midfloridasurgical.calcompose.data.models.NativeAlertSummary
import com.midfloridasurgical.calcompose.data.models.NativeDayOffRequest
import com.midfloridasurgical.calcompose.data.models.NativeHomeResponse
import com.midfloridasurgical.calcompose.data.models.NativeRequestOffResponse
import com.midfloridasurgical.calcompose.data.models.NativeScheduleAlert
import com.midfloridasurgical.calcompose.data.models.NativeSurgeon
import com.midfloridasurgical.calcompose.data.models.ScheduleDayUi
import com.midfloridasurgical.calcompose.data.models.TimeOffSubmitSegment
import com.midfloridasurgical.calcompose.data.models.emptyScheduleDay
import com.midfloridasurgical.calcompose.data.models.toUi
import com.midfloridasurgical.calcompose.util.isBenignCancel
import com.midfloridasurgical.calcompose.util.onFailureUnlessCancelled
import java.time.DayOfWeek
import java.time.LocalDate
import java.time.temporal.TemporalAdjusters

class SurgeonHomeStore(
    private val apiClient: CalApiClient,
    private val token: String,
    private val deviceToken: String,
) {
    var isLoading by mutableStateOf(false)
        private set
    private val warningMessageState = mutableStateOf<String?>(null)
    var warningMessage: String?
        get() = warningMessageState.value
        set(value) {
            // Never persist composition-leave cancel text as a user-visible banner.
            if (value != null && value == "The coroutine scope left the composition") return
            warningMessageState.value = value
        }
    var currentSurgeon by mutableStateOf<NativeSurgeon?>(null)
        private set
    var surgeons by mutableStateOf<List<NativeSurgeon>>(emptyList())
        private set
    var days by mutableStateOf<List<ScheduleDayUi>>(emptyList())
        private set
    var requests by mutableStateOf<List<NativeDayOffRequest>>(emptyList())
        private set
    var alerts by mutableStateOf(NativeAlertSummary())
        private set

    /** Union of successfully fetched windows — used to skip redundant home reloads. */
    private var coveredStart: LocalDate? = null
    private var coveredEnd: LocalDate? = null
    private var inFlightKey: String? = null

    private val daysByDate: Map<LocalDate, ScheduleDayUi>
        get() = days.associateBy { it.date }

    /**
     * Scope-style refresh with a padded window. Merges incoming days by date so a
     * narrower Schedule fetch does not wipe a wider Time Off lookahead.
     */
    suspend fun refresh(
        containing: LocalDate = LocalDate.now(),
        daysAhead: Long = 45,
        force: Boolean = false,
    ) {
        val start = containing.minusDays(7)
        val end = containing.plusDays(daysAhead)
        fetchAndMerge(start = start, end = end, force = force)
    }

    /**
     * iOS `loadLookahead`: start-of-day [containing] through [daysAhead] days ahead.
     * Default 30 for Schedule bootstrap; Time Off uses 365 / 62.
     */
    suspend fun loadLookahead(
        containing: LocalDate = LocalDate.now(),
        daysAhead: Long = 30,
        force: Boolean = false,
    ) {
        val start = containing
        val end = containing.plusDays(daysAhead)
        fetchAndMerge(start = start, end = end, force = force)
    }

    suspend fun submitTimeOff(
        start: LocalDate,
        end: LocalDate,
        reason: String,
        notes: String = "",
        segments: List<TimeOffSubmitSegment> = emptyList(),
    ): NativeRequestOffResponse {
        val response = apiClient.submitRequestOff(
            token = token,
            deviceToken = deviceToken,
            startDate = start,
            endDate = end,
            reason = reason,
            notes = notes,
            segments = segments,
        )
        loadLookahead(containing = start.withDayOfMonth(1), daysAhead = 62)
        return response
    }

    suspend fun updateTimeOff(
        requestId: Int,
        start: LocalDate,
        end: LocalDate,
        reason: String,
        notes: String = "",
        segments: List<TimeOffSubmitSegment> = emptyList(),
    ): NativeRequestOffResponse {
        val response = apiClient.updateRequestOff(
            token = token,
            deviceToken = deviceToken,
            requestId = requestId,
            startDate = start,
            endDate = end,
            reason = reason,
            notes = notes,
            segments = segments,
        )
        loadLookahead(containing = start.withDayOfMonth(1), daysAhead = 62)
        return response
    }

    suspend fun cancelTimeOff(requestId: Int, containing: LocalDate) {
        apiClient.cancelRequestOff(
            token = token,
            deviceToken = deviceToken,
            requestId = requestId,
        )
        loadLookahead(containing = containing.withDayOfMonth(1), daysAhead = 62)
    }

    suspend fun submitCallCoverage(rotationId: Int, coveringSurgeonId: Int) {
        apiClient.submitCallCoverage(
            token = token,
            deviceToken = deviceToken,
            rotationId = rotationId,
            coveringSurgeonId = coveringSurgeonId,
        )
        loadLookahead(containing = LocalDate.now(), daysAhead = 30)
    }

    suspend fun cancelCallCoverage(coverageId: Int) {
        apiClient.cancelCallCoverage(
            token = token,
            deviceToken = deviceToken,
            coverageId = coverageId,
        )
        loadLookahead(containing = LocalDate.now(), daysAhead = 30)
    }

    suspend fun createPersonalItem(
        date: LocalDate,
        title: String,
        notes: String,
        startTime: String?,
        endTime: String?,
    ) {
        apiClient.createDayItem(
            token = token,
            deviceToken = deviceToken,
            date = date,
            title = title,
            notes = notes,
            startTime = startTime,
            endTime = endTime,
        )
        loadLookahead(containing = date, daysAhead = 30)
    }

    suspend fun updatePersonalItem(
        itemId: Int,
        date: LocalDate,
        title: String,
        notes: String,
        startTime: String?,
        endTime: String?,
    ) {
        apiClient.updateDayItem(
            token = token,
            deviceToken = deviceToken,
            itemId = itemId,
            title = title,
            notes = notes,
            startTime = startTime,
            endTime = endTime,
        )
        loadLookahead(containing = date, daysAhead = 30)
    }

    suspend fun deletePersonalItem(itemId: Int, date: LocalDate) {
        apiClient.deleteDayItem(
            token = token,
            deviceToken = deviceToken,
            itemId = itemId,
        )
        loadLookahead(containing = date, daysAhead = 30)
    }

    suspend fun markAlertsRead() {
        runCatching {
            apiClient.markAlertsRead(token = token, deviceToken = deviceToken)
            alerts = NativeAlertSummary(
                unreadCount = 0,
                recent = alerts.recent.map {
                    NativeScheduleAlert(
                        id = it.id,
                        title = it.title,
                        body = it.body,
                        kind = it.kind,
                        isRead = true,
                        createdAt = it.createdAt,
                    )
                },
            )
        }.onFailureUnlessCancelled { e ->
            if (e.isBenignCancel()) return@onFailureUnlessCancelled
            warningMessage = e.message ?: "Could not mark alerts read."
        }
        loadLookahead(containing = LocalDate.now(), daysAhead = 30)
    }

    fun day(forDate: LocalDate): ScheduleDayUi =
        daysByDate[forDate] ?: emptyScheduleDay(forDate)

    /** Monday-first week — matches iOS `ClinicalCalendar.mondayFirst`. */
    fun week(containing: LocalDate): List<ScheduleDayUi> {
        val start = containing.with(TemporalAdjusters.previousOrSame(DayOfWeek.MONDAY))
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

    private suspend fun fetchAndMerge(
        start: LocalDate,
        end: LocalDate,
        force: Boolean = false,
    ) {
        val key = "$start|$end"
        if (!force && covers(start, end)) return
        if (!force && inFlightKey == key) return

        inFlightKey = key
        isLoading = true
        warningMessage = null
        try {
            runCatching {
                apiClient.fetchHome(
                    token = token,
                    deviceToken = deviceToken,
                    start = start,
                    end = end,
                )
            }.onSuccess {
                applyHome(it, fetchStart = start, fetchEnd = end)
                expandCoverage(start, end)
            }.onFailureUnlessCancelled { e ->
                if (e.isBenignCancel()) return@onFailureUnlessCancelled
                warningMessage = e.message ?: "Could not load CAL schedule."
            }
        } finally {
            if (inFlightKey == key) inFlightKey = null
            isLoading = false
        }
    }

    private fun covers(start: LocalDate, end: LocalDate): Boolean {
        val cs = coveredStart ?: return false
        val ce = coveredEnd ?: return false
        return days.isNotEmpty() && !start.isBefore(cs) && !end.isAfter(ce)
    }

    private fun expandCoverage(start: LocalDate, end: LocalDate) {
        coveredStart = coveredStart?.let { minOf(it, start) } ?: start
        coveredEnd = coveredEnd?.let { maxOf(it, end) } ?: end
    }

    /** Merge-by-date: replace days in [fetchStart, fetchEnd], keep the rest. */
    private fun applyHome(
        home: NativeHomeResponse,
        fetchStart: LocalDate,
        fetchEnd: LocalDate,
    ) {
        currentSurgeon = home.surgeon
        surgeons = home.surgeons
        val incoming = home.days.map { it.toUi() }.associateBy { it.date }
        val kept = days.filter { it.date.isBefore(fetchStart) || it.date.isAfter(fetchEnd) }
        days = (kept + incoming.values).distinctBy { it.date }.sortedBy { it.date }
        requests = mergeRequests(home.requests)
        alerts = home.alerts ?: NativeAlertSummary()
    }

    private fun mergeRequests(incoming: List<NativeDayOffRequest>): List<NativeDayOffRequest> {
        if (incoming.isEmpty()) return requests
        val byId = requests.associateBy { it.id }.toMutableMap()
        incoming.forEach { byId[it.id] = it }
        return byId.values.sortedWith(compareBy({ it.startDate }, { it.id }))
    }
}
