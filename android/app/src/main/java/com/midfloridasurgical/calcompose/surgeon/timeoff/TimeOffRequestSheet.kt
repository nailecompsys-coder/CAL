package com.midfloridasurgical.calcompose.surgeon.timeoff

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.rounded.CalendarMonth
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.DatePicker
import androidx.compose.material3.DatePickerDialog
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FilterChip
import androidx.compose.material3.Icon
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.SingleChoiceSegmentedButtonRow
import androidx.compose.material3.SegmentedButton
import androidx.compose.material3.SegmentedButtonDefaults
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.rememberDatePickerState
import androidx.compose.material3.rememberModalBottomSheetState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.midfloridasurgical.calcompose.data.models.NativeDayOffRequest
import com.midfloridasurgical.calcompose.data.models.NativeRequestOffResponse
import com.midfloridasurgical.calcompose.data.models.TimeOffSubmitSegment
import com.midfloridasurgical.calcompose.ui.theme.ClinicalPrimaryButton
import com.midfloridasurgical.calcompose.ui.theme.ClinicalPalette
import com.midfloridasurgical.calcompose.ui.theme.ClinicalTypography
import com.midfloridasurgical.calcompose.ui.theme.LiquidGlassCard
import com.midfloridasurgical.calcompose.util.onFailureUnlessCancelled
import java.time.Instant
import java.time.LocalDate
import java.time.ZoneOffset
import java.time.format.DateTimeFormatter
import java.util.Locale
import kotlinx.coroutines.launch

enum class RequestSegmentPreset(val label: String) {
    Full("Full"),
    Am("AM"),
    Pm("PM"),
}

data class RequestSegment(
    val date: LocalDate,
    val isFullDay: Boolean,
    val start: String,
    val end: String,
) {
    val preset: RequestSegmentPreset
        get() = when {
            isFullDay -> RequestSegmentPreset.Full
            start == "07:00" && end == "12:00" -> RequestSegmentPreset.Am
            start == "12:00" && end == "17:00" -> RequestSegmentPreset.Pm
            else -> RequestSegmentPreset.Full
        }

    val summary: String
        get() = if (isFullDay) "Full day" else "$start - $end"

    fun toSubmit(): TimeOffSubmitSegment = TimeOffSubmitSegment(
        date = date.toString(),
        isFullDay = isFullDay,
        start = start,
        end = end,
    )

    companion object {
        fun fromPreset(date: LocalDate, preset: RequestSegmentPreset): RequestSegment =
            when (preset) {
                RequestSegmentPreset.Full ->
                    RequestSegment(date, isFullDay = true, start = "07:00", end = "17:00")
                RequestSegmentPreset.Am ->
                    RequestSegment(date, isFullDay = false, start = "07:00", end = "12:00")
                RequestSegmentPreset.Pm ->
                    RequestSegment(date, isFullDay = false, start = "12:00", end = "17:00")
            }
    }
}

private val Reasons = listOf("Day Off", "No Call", "Vacation", "CME", "Partial Day", "Medical")
private val DisplayDate = DateTimeFormatter.ofPattern("MMM d, yyyy", Locale.US)
private val SegmentDate = DateTimeFormatter.ofPattern("MM/dd", Locale.US)

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun TimeOffRequestSheet(
    existing: NativeDayOffRequest? = null,
    defaultDate: LocalDate = LocalDate.now(),
    onDismiss: () -> Unit,
    onSubmit: suspend (
        start: LocalDate,
        end: LocalDate,
        reason: String,
        notes: String,
        segments: List<TimeOffSubmitSegment>,
    ) -> NativeRequestOffResponse,
) {
    val sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = true)
    val scope = rememberCoroutineScope()

    val isEditing = existing != null
    val seedDate = if (defaultDate.isBefore(LocalDate.now())) LocalDate.now() else defaultDate
    var startDate by remember(existing, seedDate) {
        mutableStateOf(existing?.startDate?.let { runCatching { LocalDate.parse(it) }.getOrNull() } ?: seedDate)
    }
    var endDate by remember(existing, seedDate) {
        mutableStateOf(existing?.endDate?.let { runCatching { LocalDate.parse(it) }.getOrNull() } ?: seedDate)
    }
    var segments by remember(existing, seedDate) {
        mutableStateOf(existing?.toRequestSegments() ?: listOf(RequestSegment.fromPreset(seedDate, RequestSegmentPreset.Full)))
    }
    var reason by remember(existing) {
        mutableStateOf(existing?.reason?.takeIf { Reasons.contains(it) } ?: Reasons.first())
    }
    var notes by remember(existing) { mutableStateOf(existing?.notes.orEmpty()) }
    var message by remember { mutableStateOf<String?>(null) }
    var isSubmitting by remember { mutableStateOf(false) }
    var receipt by remember { mutableStateOf<TimeOffReceipt?>(null) }
    var editingField by remember { mutableStateOf<DateField?>(null) }

    fun normalizeSegments() {
        val existing = segments.associateBy { it.date }
        val dates = datesBetween(startDate, endDate)
        segments = dates.map { date ->
            existing[date] ?: RequestSegment.fromPreset(date, RequestSegmentPreset.Full)
        }
    }

    LaunchedEffect(startDate, endDate) {
        if (endDate.isBefore(startDate)) endDate = startDate
        if (startDate.isAfter(endDate)) startDate = endDate
        normalizeSegments()
    }

    ModalBottomSheet(
        onDismissRequest = { if (!isSubmitting) onDismiss() },
        sheetState = sheetState,
        containerColor = ClinicalPalette.PageMiddle,
    ) {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .verticalScroll(rememberScrollState())
                .padding(horizontal = 16.dp, vertical = 8.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            receipt?.let { sent ->
                TimeOffReceiptContent(receipt = sent, isUpdate = isEditing, onOk = onDismiss)
            } ?: run {
            Text(
                if (isEditing) "Modify Time Off" else "Request Time Off",
                style = ClinicalTypography.headlineStrong,
                color = ClinicalPalette.Ink,
            )
            if (existing?.status.equals("approved", ignoreCase = true)) {
                Text(
                    "Changing this sends it back for approval.",
                    color = ClinicalPalette.WarningText,
                    style = ClinicalTypography.caption,
                )
            }

            SectionLabel("Range")
            RequestDateButton("Start", startDate) { editingField = DateField.Start }
            RequestDateButton("End", endDate) { editingField = DateField.End }

            message?.let {
                LiquidGlassCard(tint = ClinicalPalette.Amber, cornerRadius = 12.dp) {
                    Text(
                        it,
                        color = ClinicalPalette.Muted,
                        style = ClinicalTypography.caption,
                        modifier = Modifier.padding(10.dp),
                    )
                }
            }

            Text(
                if (segments.size == 1) "1 day selected." else "${segments.size} days selected.",
                color = ClinicalPalette.Muted,
                style = ClinicalTypography.captionEmphasized,
            )

            SectionLabel("Days")
            segments.forEach { segment ->
                RequestSegmentRow(segment = segment) { preset ->
                    segments = segments.map {
                        if (it.date == segment.date) {
                            RequestSegment.fromPreset(it.date, preset)
                        } else {
                            it
                        }
                    }
                }
            }

            SectionLabel("Details")
            Text(
                "Type",
                style = ClinicalTypography.caption,
                color = ClinicalPalette.Muted,
            )
            Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
                Reasons.chunked(3).forEach { row ->
                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        horizontalArrangement = Arrangement.spacedBy(6.dp),
                    ) {
                        row.forEach { item ->
                            FilterChip(
                                selected = reason == item,
                                onClick = { reason = item },
                                label = { Text(item, style = ClinicalTypography.caption, maxLines = 1) },
                                modifier = Modifier.weight(1f),
                            )
                        }
                        repeat(3 - row.size) {
                            Spacer(modifier = Modifier.weight(1f))
                        }
                    }
                }
            }

            OutlinedTextField(
                value = notes,
                onValueChange = { notes = it },
                label = { Text("Optional note") },
                modifier = Modifier.fillMaxWidth(),
                minLines = 3,
            )

            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                TextButton(
                    onClick = onDismiss,
                    enabled = !isSubmitting,
                    modifier = Modifier.weight(1f),
                ) {
                    Text("Cancel", color = ClinicalPalette.Muted, style = ClinicalTypography.rowTitle)
                }
                Button(
                    onClick = {
                        scope.launch {
                            isSubmitting = true
                            message = null
                            try {
                                runCatching {
                                    onSubmit(
                                        startDate,
                                        endDate,
                                        reason,
                                        notes.trim(),
                                        segments.map { it.toSubmit() },
                                    )
                                }.onSuccess { result ->
                                    receipt = TimeOffReceipt(
                                        startDate = startDate,
                                        endDate = endDate,
                                        reason = reason,
                                        notes = notes.trim(),
                                        segments = segments,
                                        warnings = result.warnings,
                                    )
                                }.onFailureUnlessCancelled { error ->
                                    message = error.message ?: "Could not submit time off."
                                }
                            } finally {
                                isSubmitting = false
                            }
                        }
                    },
                    enabled = !isSubmitting,
                    modifier = Modifier.weight(1f),
                    colors = ButtonDefaults.buttonColors(
                        containerColor = ClinicalPalette.Teal,
                        contentColor = ClinicalPalette.OnTeal,
                    ),
                    shape = RoundedCornerShape(12.dp),
                ) {
                    Text(
                        if (isSubmitting) "Saving" else if (isEditing) "Save" else "Submit",
                        style = ClinicalTypography.rowTitleStrong,
                    )
                }
            }
            }

            Spacer(modifier = Modifier.height(20.dp))
        }
    }

    editingField?.let { field ->
        val initial = if (field == DateField.Start) startDate else endDate
        val pickerState = rememberDatePickerState(
            initialSelectedDateMillis = initial.atStartOfDay(ZoneOffset.UTC).toInstant().toEpochMilli(),
        )
        DatePickerDialog(
            onDismissRequest = { editingField = null },
            confirmButton = {
                TextButton(
                    onClick = {
                        val millis = pickerState.selectedDateMillis
                        if (millis != null) {
                            val picked = Instant.ofEpochMilli(millis)
                                .atZone(ZoneOffset.UTC)
                                .toLocalDate()
                            when (field) {
                                DateField.Start -> {
                                    startDate = picked
                                    if (endDate.isBefore(picked)) endDate = picked
                                }
                                DateField.End -> {
                                    endDate = picked
                                    if (endDate.isBefore(startDate)) startDate = endDate
                                }
                            }
                        }
                        editingField = null
                    },
                ) {
                    Text("Done", color = ClinicalPalette.Teal, style = ClinicalTypography.caption)
                }
            },
            dismissButton = {
                TextButton(onClick = { editingField = null }) {
                    Text("Cancel", color = ClinicalPalette.Muted)
                }
            },
        ) {
            DatePicker(state = pickerState)
        }
    }
}

private data class TimeOffReceipt(
    val startDate: LocalDate,
    val endDate: LocalDate,
    val reason: String,
    val notes: String,
    val segments: List<RequestSegment>,
    val warnings: List<String>,
) {
    val rangeLabel: String
        get() {
            val start = startDate.format(DisplayDate)
            if (startDate == endDate) return start
            return "$start – ${endDate.format(DisplayDate)}"
        }
}

@Composable
private fun TimeOffReceiptContent(
    receipt: TimeOffReceipt,
    isUpdate: Boolean,
    onOk: () -> Unit,
) {
    Text(
        if (isUpdate) "Request Updated" else "Request Sent",
        style = ClinicalTypography.headlineStrong,
        color = ClinicalPalette.Ink,
    )
    SectionLabel("Sent")
    LiquidGlassCard(tint = ClinicalPalette.CardStrong, cornerRadius = 12.dp) {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .padding(horizontal = 12.dp, vertical = 10.dp),
            verticalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            ReceiptRow("Dates", receipt.rangeLabel)
            ReceiptRow("Type", receipt.reason)
            if (receipt.notes.isNotBlank()) {
                ReceiptRow("Note", receipt.notes)
            }
            ReceiptRow("Status", "Pending approval")
        }
    }
    SectionLabel("Days")
    receipt.segments.forEach { segment ->
        LiquidGlassCard(tint = ClinicalPalette.PorcelainChip, cornerRadius = 12.dp) {
            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(horizontal = 10.dp, vertical = 8.dp),
                horizontalArrangement = Arrangement.SpaceBetween,
            ) {
                Text(
                    segment.date.format(SegmentDate),
                    style = ClinicalTypography.rowTitle,
                    color = ClinicalPalette.Ink,
                )
                Text(
                    segment.summary,
                    style = ClinicalTypography.captionEmphasized,
                    color = ClinicalPalette.Muted,
                )
            }
        }
    }
    primaryWarning(receipt.warnings)?.let { warning ->
        LiquidGlassCard(tint = ClinicalPalette.Amber, cornerRadius = 12.dp) {
            Text(
                cleanWarning(warning),
                color = ClinicalPalette.WarningText,
                style = ClinicalTypography.caption,
                modifier = Modifier.padding(10.dp),
            )
        }
    }
    ClinicalPrimaryButton(text = "OK", onClick = onOk)
}

@Composable
private fun ReceiptRow(title: String, value: String) {
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.SpaceBetween,
    ) {
        Text(title, style = ClinicalTypography.rowTitle, color = ClinicalPalette.Ink)
        Text(value, style = ClinicalTypography.rowTitle, color = ClinicalPalette.Teal)
    }
}

private enum class DateField { Start, End }

@Composable
private fun SectionLabel(title: String) {
    Text(
        title.uppercase(Locale.US),
        color = ClinicalPalette.Muted,
        style = ClinicalTypography.sectionLabel,
    )
}

@Composable
private fun RequestDateButton(title: String, date: LocalDate, onClick: () -> Unit) {
    LiquidGlassCard(tint = ClinicalPalette.CardStrong, cornerRadius = 12.dp) {
        TextButton(
            onClick = onClick,
            modifier = Modifier.fillMaxWidth(),
        ) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Text(title, style = ClinicalTypography.rowTitle, color = ClinicalPalette.Ink)
                Row(
                    horizontalArrangement = Arrangement.spacedBy(6.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Text(
                        date.format(DisplayDate),
                        style = ClinicalTypography.rowTitle,
                        color = ClinicalPalette.Teal,
                    )
                    Icon(
                        Icons.Rounded.CalendarMonth,
                        contentDescription = null,
                        tint = ClinicalPalette.Teal,
                    )
                }
            }
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun RequestSegmentRow(
    segment: RequestSegment,
    onChange: (RequestSegmentPreset) -> Unit,
) {
    LiquidGlassCard(tint = ClinicalPalette.PorcelainChip, cornerRadius = 12.dp) {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .padding(horizontal = 10.dp, vertical = 8.dp),
            verticalArrangement = Arrangement.spacedBy(6.dp),
        ) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
            ) {
                Text(
                    segment.date.format(SegmentDate),
                    style = ClinicalTypography.rowTitle,
                    color = ClinicalPalette.Ink,
                )
                Text(
                    segment.summary,
                    style = ClinicalTypography.captionEmphasized,
                    color = ClinicalPalette.Muted,
                )
            }
            SingleChoiceSegmentedButtonRow(modifier = Modifier.fillMaxWidth()) {
                RequestSegmentPreset.entries.forEachIndexed { index, preset ->
                    SegmentedButton(
                        selected = segment.preset == preset,
                        onClick = { onChange(preset) },
                        shape = SegmentedButtonDefaults.itemShape(
                            index = index,
                            count = RequestSegmentPreset.entries.size,
                        ),
                    ) {
                        Text(preset.label, style = ClinicalTypography.caption)
                    }
                }
            }
        }
    }
}

private fun NativeDayOffRequest.toRequestSegments(): List<RequestSegment> {
    if (segments.isNotEmpty()) {
        return segments.mapNotNull { segment ->
            val date = runCatching { LocalDate.parse(segment.date) }.getOrNull() ?: return@mapNotNull null
            if (segment.isFullDay) {
                RequestSegment.fromPreset(date, RequestSegmentPreset.Full)
            } else if (segment.start == "07:00" && segment.end == "12:00") {
                RequestSegment.fromPreset(date, RequestSegmentPreset.Am)
            } else if (segment.start == "12:00" && segment.end == "17:00") {
                RequestSegment.fromPreset(date, RequestSegmentPreset.Pm)
            } else {
                RequestSegment(
                    date = date,
                    isFullDay = false,
                    start = segment.start ?: "07:00",
                    end = segment.end ?: "17:00",
                )
            }
        }
    }
    val start = runCatching { LocalDate.parse(startDate) }.getOrNull() ?: return emptyList()
    val end = runCatching { LocalDate.parse(endDate) }.getOrNull() ?: start
    return datesBetween(start, end).map { RequestSegment.fromPreset(it, RequestSegmentPreset.Full) }
}

private fun datesBetween(start: LocalDate, end: LocalDate): List<LocalDate> {
    val dates = mutableListOf<LocalDate>()
    var cursor = start
    while (!cursor.isAfter(end)) {
        dates.add(cursor)
        cursor = cursor.plusDays(1)
    }
    return dates
}

private fun primaryWarning(warnings: List<String>): String? =
    warnings.firstOrNull {
        it.contains("already has", ignoreCase = true) &&
            it.contains("approved off", ignoreCase = true)
    } ?: warnings.firstOrNull()

private fun cleanWarning(warning: String): String {
    var cleaned = warning
        .replace("Heads up: ", "")
        .replace("Submitted. ", "")
        .trim()
    if (!cleaned.endsWith(".")) cleaned += "."
    return cleaned
}
