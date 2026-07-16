package com.midfloridasurgical.calcompose.surgeon.schedule

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.Button
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
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.midfloridasurgical.calcompose.data.models.CallAssignmentUi
import com.midfloridasurgical.calcompose.data.models.NativeSurgeon
import com.midfloridasurgical.calcompose.ui.theme.ClinicalPalette

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun CallCoverageSheet(
    assignment: CallAssignmentUi,
    surgeons: List<NativeSurgeon>,
    isSaving: Boolean,
    onDismiss: () -> Unit,
    onSave: (coveringSurgeonId: Int) -> Unit,
) {
    val sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = true)
    var selectedId by remember {
        mutableStateOf(assignment.coveringSurgeonId ?: surgeons.firstOrNull()?.id)
    }

    ModalBottomSheet(
        onDismissRequest = onDismiss,
        sheetState = sheetState,
    ) {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .padding(horizontal = 20.dp, vertical = 8.dp),
            verticalArrangement = Arrangement.spacedBy(10.dp),
        ) {
            Text("Call coverage", fontWeight = FontWeight.Bold, fontSize = 20.sp)
            Text(
                "${assignment.group} · currently ${assignment.displayInitials}",
                color = ClinicalPalette.Muted,
                fontSize = 13.sp,
            )

            if (surgeons.isEmpty()) {
                Text("No eligible covering surgeons loaded.", color = ClinicalPalette.Muted)
            } else {
                LazyColumn(
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(vertical = 4.dp),
                    verticalArrangement = Arrangement.spacedBy(4.dp),
                ) {
                    items(surgeons, key = { it.id }) { surgeon ->
                        val selected = surgeon.id == selectedId
                        Text(
                            "${surgeon.initials} · ${surgeon.name}",
                            modifier = Modifier
                                .fillMaxWidth()
                                .clickable { selectedId = surgeon.id }
                                .padding(vertical = 10.dp),
                            fontWeight = if (selected) FontWeight.Bold else FontWeight.Normal,
                            color = if (selected) ClinicalPalette.Teal else ClinicalPalette.Ink,
                        )
                    }
                }
            }

            Button(
                onClick = { selectedId?.let(onSave) },
                enabled = !isSaving && selectedId != null,
                modifier = Modifier.fillMaxWidth(),
            ) {
                Text(if (isSaving) "Saving…" else "Assign coverage")
            }
            TextButton(onClick = onDismiss, modifier = Modifier.fillMaxWidth()) {
                Text("Cancel")
            }
        }
    }
}
