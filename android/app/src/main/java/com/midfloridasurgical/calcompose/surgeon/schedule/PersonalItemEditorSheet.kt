package com.midfloridasurgical.calcompose.surgeon.schedule

import androidx.compose.foundation.clickable
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
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FilterChip
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TimePicker
import androidx.compose.material3.rememberModalBottomSheetState
import androidx.compose.material3.rememberTimePickerState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.midfloridasurgical.calcompose.data.models.PersonalItemPresets
import com.midfloridasurgical.calcompose.data.models.PersonalItemUi
import com.midfloridasurgical.calcompose.ui.theme.ClinicalPalette
import com.midfloridasurgical.calcompose.ui.theme.ClinicalTypography
import com.midfloridasurgical.calcompose.ui.theme.LiquidGlassCard
import java.time.LocalDate
import java.time.format.DateTimeFormatter
import java.time.format.TextStyle
import java.util.Locale
import kotlinx.coroutines.launch

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun PersonalItemEditorSheet(
    date: LocalDate,
    item: PersonalItemUi?,
    onDismiss: () -> Unit,
    onSave: suspend (title: String, notes: String, start: String?, end: String?) -> Unit,
    onDelete: (suspend () -> Unit)?,
) {
    val sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = true)
    val scope = rememberCoroutineScope()

    val existing = (item?.title ?: "").trim()
    var selectedType by remember {
        mutableStateOf(
            when {
                existing.isEmpty() -> PersonalItemPresets.titles.first()
                existing in PersonalItemPresets.titles && existing != PersonalItemPresets.OTHER ->
                    existing
                else -> PersonalItemPresets.OTHER
            },
        )
    }
    var customTitle by remember {
        mutableStateOf(
            if (existing.isNotEmpty() &&
                (existing !in PersonalItemPresets.titles || existing == PersonalItemPresets.OTHER)
            ) {
                existing
            } else {
                ""
            },
        )
    }
    var notes by remember { mutableStateOf(item?.notes.orEmpty()) }
    var hasTime by remember { mutableStateOf(!(item?.start.isNullOrBlank())) }
    var startTime by remember { mutableStateOf(item?.start?.takeIf { it.isNotBlank() } ?: "07:00") }
    var endTime by remember {
        mutableStateOf(
            item?.end?.takeIf { it.isNotBlank() } ?: "08:00",
        )
    }
    var editingTime by remember { mutableStateOf<TimeField?>(null) }
    var isSaving by remember { mutableStateOf(false) }
    var errorMessage by remember { mutableStateOf<String?>(null) }

    val resolvedTitle = if (selectedType == PersonalItemPresets.OTHER) {
        customTitle.trim()
    } else {
        selectedType
    }
    val canSave = resolvedTitle.isNotEmpty() && !isSaving

    val headerDate = date.dayOfWeek.getDisplayName(TextStyle.FULL, Locale.US) +
        " · " + date.format(DateTimeFormatter.ofPattern("MMM d", Locale.US))

    ModalBottomSheet(
        onDismissRequest = { if (!isSaving) onDismiss() },
        sheetState = sheetState,
        containerColor = ClinicalPalette.Card,
    ) {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .verticalScroll(rememberScrollState())
                .padding(horizontal = 16.dp, vertical = 8.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            Text(
                if (item == null) "Add Personal Item" else "Edit Personal Item",
                style = ClinicalTypography.headlineStrong,
                color = ClinicalPalette.Ink,
            )
            Text(headerDate, color = ClinicalPalette.Muted, style = ClinicalTypography.caption)

            Text(
                "Type",
                style = ClinicalTypography.sectionLabel,
                color = ClinicalPalette.Muted,
            )
            Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
                PersonalItemPresets.titles.chunked(2).forEach { row ->
                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        horizontalArrangement = Arrangement.spacedBy(8.dp),
                    ) {
                        row.forEach { title ->
                            FilterChip(
                                selected = selectedType == title,
                                onClick = { selectedType = title },
                                label = { Text(title, style = ClinicalTypography.caption, maxLines = 1) },
                                modifier = Modifier.weight(1f),
                            )
                        }
                        if (row.size == 1) {
                            Spacer(modifier = Modifier.weight(1f))
                        }
                    }
                }
            }

            if (selectedType == PersonalItemPresets.OTHER) {
                OutlinedTextField(
                    value = customTitle,
                    onValueChange = { customTitle = it },
                    label = { Text("Title") },
                    modifier = Modifier.fillMaxWidth(),
                    singleLine = true,
                )
            }

            OutlinedTextField(
                value = notes,
                onValueChange = { notes = it },
                label = { Text("Notes (optional)") },
                modifier = Modifier.fillMaxWidth(),
            )

            LiquidGlassCard(tint = ClinicalPalette.PorcelainChip, cornerRadius = 12.dp) {
                Row(
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(horizontal = 12.dp, vertical = 8.dp),
                    verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.SpaceBetween,
                ) {
                    Text("Add time", style = ClinicalTypography.rowTitle, color = ClinicalPalette.Ink)
                    Switch(checked = hasTime, onCheckedChange = { hasTime = it })
                }
            }

            if (hasTime) {
                TimePickerField(
                    label = "Start",
                    value = startTime,
                    onClick = { editingTime = TimeField.Start },
                )
                TimePickerField(
                    label = "End",
                    value = endTime,
                    onClick = { editingTime = TimeField.End },
                )
            }

            errorMessage?.let {
                Text(
                    it,
                    color = ClinicalPalette.WarningText,
                    style = ClinicalTypography.caption,
                )
            }

            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                TextButton(
                    onClick = onDismiss,
                    enabled = !isSaving,
                    modifier = Modifier.weight(1f),
                ) {
                    Text("Cancel", color = ClinicalPalette.Muted, style = ClinicalTypography.rowTitle)
                }
                Button(
                    onClick = {
                        scope.launch {
                            isSaving = true
                            errorMessage = null
                            runCatching {
                                onSave(
                                    resolvedTitle,
                                    notes.trim(),
                                    if (hasTime) startTime.trim().ifBlank { null } else null,
                                    if (hasTime) endTime.trim().ifBlank { null } else null,
                                )
                            }.onSuccess {
                                onDismiss()
                            }.onFailure { error ->
                                errorMessage = error.message ?: "Could not save personal item."
                            }
                            isSaving = false
                        }
                    },
                    enabled = canSave,
                    modifier = Modifier.weight(1f),
                    colors = ButtonDefaults.buttonColors(
                        containerColor = ClinicalPalette.Teal,
                        contentColor = ClinicalPalette.OnTeal,
                    ),
                    shape = RoundedCornerShape(12.dp),
                ) {
                    Text(
                        if (item == null) "Add" else "Save",
                        style = ClinicalTypography.rowTitleStrong,
                    )
                }
            }

            if (item != null && onDelete != null) {
                Button(
                    onClick = {
                        scope.launch {
                            isSaving = true
                            errorMessage = null
                            runCatching { onDelete() }
                                .onSuccess { onDismiss() }
                                .onFailure { error ->
                                    errorMessage = error.message ?: "Could not delete personal item."
                                }
                            isSaving = false
                        }
                    },
                    enabled = !isSaving,
                    modifier = Modifier.fillMaxWidth(),
                    colors = ButtonDefaults.buttonColors(
                        containerColor = ClinicalPalette.Block,
                        contentColor = ClinicalPalette.Ink,
                    ),
                    shape = RoundedCornerShape(12.dp),
                ) {
                    Text("Delete personal item", style = ClinicalTypography.rowTitleStrong)
                }
            }

            Spacer(modifier = Modifier.height(16.dp))
        }
    }

    editingTime?.let { field ->
        val current = if (field == TimeField.Start) startTime else endTime
        val parts = current.split(":")
        val hour = parts.firstOrNull()?.toIntOrNull() ?: 7
        val minute = parts.getOrNull(1)?.toIntOrNull() ?: 0
        val pickerState = rememberTimePickerState(
            initialHour = hour.coerceIn(0, 23),
            initialMinute = minute.coerceIn(0, 59),
            is24Hour = true,
        )
        AlertDialog(
            onDismissRequest = { editingTime = null },
            confirmButton = {
                TextButton(
                    onClick = {
                        val hhmm = "%02d:%02d".format(pickerState.hour, pickerState.minute)
                        when (field) {
                            TimeField.Start -> startTime = hhmm
                            TimeField.End -> endTime = hhmm
                        }
                        editingTime = null
                    },
                ) {
                    Text("Done", color = ClinicalPalette.Teal, style = ClinicalTypography.caption)
                }
            },
            dismissButton = {
                TextButton(onClick = { editingTime = null }) {
                    Text("Cancel", color = ClinicalPalette.Muted)
                }
            },
            title = {
                Text(
                    if (field == TimeField.Start) "Start time" else "End time",
                    style = ClinicalTypography.headline,
                )
            },
            text = {
                TimePicker(state = pickerState)
            },
            containerColor = ClinicalPalette.Card,
        )
    }
}

private enum class TimeField { Start, End }

@Composable
private fun TimePickerField(
    label: String,
    value: String,
    onClick: () -> Unit,
) {
    LiquidGlassCard(tint = ClinicalPalette.CardStrong, cornerRadius = 12.dp) {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .clickable(onClick = onClick)
                .padding(horizontal = 12.dp, vertical = 12.dp),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Text(label, style = ClinicalTypography.rowTitle, color = ClinicalPalette.Ink)
            Text(
                displayTime12(value),
                style = ClinicalTypography.rowTitle,
                color = ClinicalPalette.Teal,
            )
        }
    }
}

private fun displayTime12(value: String): String {
    val parts = value.split(":")
    val hour24 = parts.firstOrNull()?.toIntOrNull() ?: return value
    val minute = parts.getOrNull(1) ?: "00"
    val hour12 = ((hour24 + 11) % 12) + 1
    val suffix = if (hour24 >= 12) "PM" else "AM"
    return "$hour12:$minute $suffix"
}
