package com.midfloridasurgical.calcompose.surgeon.schedule

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.rememberModalBottomSheetState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.drawBehind
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.unit.TextUnit
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.midfloridasurgical.calcompose.data.models.CallAssignmentUi
import com.midfloridasurgical.calcompose.data.models.NativeSurgeon
import com.midfloridasurgical.calcompose.ui.theme.ClinicalPalette
import com.midfloridasurgical.calcompose.ui.theme.ClinicalTypography
import com.midfloridasurgical.calcompose.ui.theme.LiquidGlassCard

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun CallCoverageSheet(
    assignment: CallAssignmentUi,
    surgeons: List<NativeSurgeon>,
    isSaving: Boolean,
    onDismiss: () -> Unit,
    onSave: (coveringSurgeonId: Int) -> Unit,
    onClearCoverage: (() -> Unit)? = null,
) {
    val sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = true)
    // Match iOS: never preselect a covering surgeon.
    var selectedId by remember(assignment.rotationId) { mutableStateOf<Int?>(null) }
    val selectedSurgeon = surgeons.firstOrNull { it.id == selectedId }
    val canSave = selectedId != null && !isSaving
    val canClear = assignment.isCovered &&
        assignment.coverageId != null &&
        onClearCoverage != null &&
        !isSaving

    ModalBottomSheet(
        onDismissRequest = onDismiss,
        sheetState = sheetState,
        containerColor = ClinicalPalette.Card,
    ) {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .padding(horizontal = 16.dp, vertical = 8.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            Text(
                "Cover On Call",
                style = ClinicalTypography.headlineStrong,
                color = ClinicalPalette.Ink,
            )

            LiquidGlassCard(tint = ClinicalPalette.CardStrong, cornerRadius = 18.dp) {
                Column(
                    modifier = Modifier.padding(14.dp),
                    verticalArrangement = Arrangement.spacedBy(6.dp),
                ) {
                    Text(
                        assignment.locationShort,
                        style = ClinicalTypography.headline,
                        color = ClinicalPalette.Ink,
                        maxLines = 2,
                    )
                    Row(
                        horizontalArrangement = Arrangement.spacedBy(6.dp),
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        StruckOrPlainInitials(
                            text = assignment.originalInitials,
                            struck = assignment.isCovered,
                        )
                        Text("→", color = ClinicalPalette.Muted, style = ClinicalTypography.caption)
                        Text(
                            selectedSurgeon?.initials ?: "—",
                            style = ClinicalTypography.monoCaption,
                            color = if (selectedSurgeon == null) {
                                ClinicalPalette.Muted
                            } else {
                                ClinicalPalette.Ink
                            },
                        )
                    }
                    if (selectedSurgeon == null) {
                        Text(
                            "Select covering surgeon",
                            color = ClinicalPalette.Muted,
                            style = ClinicalTypography.caption,
                        )
                    }
                }
            }

            if (surgeons.isEmpty()) {
                LiquidGlassCard(tint = ClinicalPalette.Amber, cornerRadius = 16.dp) {
                    Text(
                        "No eligible covering surgeons loaded",
                        color = ClinicalPalette.Muted,
                        style = ClinicalTypography.caption,
                        modifier = Modifier.padding(14.dp),
                    )
                }
            } else {
                LazyColumn(
                    modifier = Modifier
                        .fillMaxWidth()
                        .height(280.dp),
                    verticalArrangement = Arrangement.spacedBy(8.dp),
                ) {
                    items(surgeons, key = { it.id }) { surgeon ->
                        val selected = surgeon.id == selectedId
                        Row(
                            modifier = Modifier
                                .fillMaxWidth()
                                .background(
                                    if (selected) ClinicalPalette.TealSoft else ClinicalPalette.Card,
                                    RoundedCornerShape(15.dp),
                                )
                                .border(
                                    width = 1.dp,
                                    color = if (selected) ClinicalPalette.Teal else ClinicalPalette.Stroke,
                                    shape = RoundedCornerShape(15.dp),
                                )
                                .clickable { selectedId = surgeon.id }
                                .padding(horizontal = 12.dp, vertical = 10.dp),
                            horizontalArrangement = Arrangement.spacedBy(10.dp),
                            verticalAlignment = Alignment.CenterVertically,
                        ) {
                            Text(
                                surgeon.initials,
                                style = ClinicalTypography.monoCaption,
                                color = ClinicalPalette.Teal,
                            )
                            Column(modifier = Modifier.weight(1f)) {
                                Text(
                                    surgeon.name,
                                    style = ClinicalTypography.rowTitle,
                                    color = ClinicalPalette.Ink,
                                    maxLines = 1,
                                )
                                Text(
                                    if (surgeon.staffType == "physician") "Surgeon" else "PA / Staff",
                                    color = ClinicalPalette.Muted,
                                    style = ClinicalTypography.captionEmphasized,
                                )
                            }
                            if (selected) {
                                Text("✓", color = ClinicalPalette.Teal, style = ClinicalTypography.rowTitleStrong)
                            }
                        }
                    }
                }
            }

            Button(
                onClick = { selectedId?.let(onSave) },
                enabled = canSave,
                modifier = Modifier.fillMaxWidth(),
                colors = ButtonDefaults.buttonColors(
                    containerColor = ClinicalPalette.Teal,
                    disabledContainerColor = ClinicalPalette.Muted,
                    contentColor = ClinicalPalette.OnTeal,
                    disabledContentColor = ClinicalPalette.OnTeal,
                ),
                shape = RoundedCornerShape(14.dp),
            ) {
                Text(
                    when {
                        isSaving -> "Saving…"
                        assignment.isCovered -> "Update Coverage"
                        else -> "Save Coverage"
                    },
                    style = ClinicalTypography.rowTitle,
                    modifier = Modifier.padding(vertical = 4.dp),
                )
            }

            if (canClear) {
                Button(
                    onClick = { onClearCoverage?.invoke() },
                    enabled = !isSaving,
                    modifier = Modifier.fillMaxWidth(),
                    colors = ButtonDefaults.buttonColors(
                        containerColor = ClinicalPalette.Amber,
                        contentColor = ClinicalPalette.Ink,
                    ),
                    shape = RoundedCornerShape(14.dp),
                ) {
                    Text(
                        "Clear Coverage",
                        style = ClinicalTypography.rowTitle,
                        modifier = Modifier.padding(vertical = 4.dp),
                    )
                }
            }

            TextButton(onClick = onDismiss, modifier = Modifier.fillMaxWidth()) {
                Text("Cancel", color = ClinicalPalette.Muted, style = ClinicalTypography.rowTitle)
            }
            Spacer(modifier = Modifier.height(8.dp))
        }
    }
}

@Composable
fun StruckOrPlainInitials(
    text: String,
    struck: Boolean,
    modifier: Modifier = Modifier,
    fontSize: TextUnit = 18.sp,
) {
    val color = ClinicalPalette.CoverageRed
    Text(
        text = text,
        modifier = modifier.then(
            if (struck) {
                Modifier.drawBehind {
                    val y = size.height / 2f
                    drawLine(
                        color = color,
                        start = Offset(0f, y),
                        end = Offset(size.width, y),
                        strokeWidth = 3f,
                    )
                }
            } else {
                Modifier
            },
        ),
        style = ClinicalTypography.monoCaption.copy(fontSize = fontSize),
        color = color,
    )
}

@Composable
fun CoverageInitialsChip(
    assignment: CallAssignmentUi,
    modifier: Modifier = Modifier,
) {
    if (assignment.isCovered) {
        Row(
            modifier = modifier,
            horizontalArrangement = Arrangement.spacedBy(2.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            StruckOrPlainInitials(
                text = assignment.originalInitials,
                struck = true,
                fontSize = 12.sp,
            )
            Text(
                assignment.coveringInitials ?: assignment.displayInitials,
                style = ClinicalTypography.monoChip,
                color = ClinicalPalette.Ink,
            )
        }
    } else {
        Text(
            assignment.displayInitials,
            modifier = modifier,
            style = ClinicalTypography.monoChip,
            color = ClinicalPalette.CoverageRed,
        )
    }
}
