package com.midfloridasurgical.calcompose.surgeon.schedule

import androidx.compose.animation.AnimatedVisibility
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.rounded.ExpandMore
import androidx.compose.material3.Icon
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.rotate
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.midfloridasurgical.calcompose.data.models.ScheduleItemUi
import com.midfloridasurgical.calcompose.ui.theme.ClinicalPalette
import java.util.Locale

/** Mirrors iOS `ClinicOrFacilityGroup`. */
data class ClinicOrFacilityGroup(
    val id: String,
    val title: String,
    val timeRange: String,
    val details: List<ClinicOrDetailRow>,
    val countStyle: CountStyle,
) {
    enum class CountStyle { Cases, Visits }

    val headerTitle: String
        get() {
            val count = details.size
            return when (countStyle) {
                CountStyle.Cases -> {
                    val noun = if (count == 1) "Case" else "Cases"
                    "$title - $count $noun"
                }
                CountStyle.Visits -> {
                    val noun = if (count == 1) "Visit" else "Visits"
                    "$title - $count $noun"
                }
            }
        }
}

data class ClinicOrDetailRow(
    val id: String,
    val time: String,
    val primary: String,
    val secondary: String,
)

/**
 * Port of iOS `ClinicOrScheduleBuilder` — facility headers with nested cases/visits.
 * Hides Block OR rows; Aprima Surgery One / IPA + hospital outpt nest under facilities.
 */
object ClinicOrScheduleBuilder {
    fun groups(from: List<ScheduleItemUi>): List<ClinicOrFacilityGroup> {
        val visible = from.filter { it.kind != "block_or" }
        val clinics = visible.filter { it.kind == "clinic" }
        val surgeries = visible.filter { it.kind == "surgery" }
        val claimed = mutableSetOf<String>()
        val groups = mutableListOf<ClinicOrFacilityGroup>()

        for (clinic in clinics) {
            val matched = surgeries.filter { surgeryBelongs(it, to = clinic) }
            matched.forEach { claimed.add(it.id) }
            val isOR = looksLikeOperatingRoom(clinic.title)

            val details = when {
                isOR -> matched.sortedBy { it.start }.map { surgeryDetail(it) }
                matched.isNotEmpty() -> {
                    val fromAprima = matched.sortedBy { it.start }.map { surgeryDetail(it) }
                    val fromNotes = parseClinicVisits(clinic.notes)
                    mergeDetails(fromAprima, fromNotes)
                }
                else -> parseClinicVisits(clinic.notes)
            }

            groups.add(
                ClinicOrFacilityGroup(
                    id = clinic.id,
                    title = clinic.title,
                    timeRange = expandedTimeRange(clinic, matched),
                    details = details,
                    countStyle = if (isOR) {
                        ClinicOrFacilityGroup.CountStyle.Cases
                    } else {
                        ClinicOrFacilityGroup.CountStyle.Visits
                    },
                ),
            )
        }

        val leftover = surgeries.filter { it.id !in claimed }
        val byLocation = leftover.groupBy { locationKey(it) }
        for (key in byLocation.keys.sorted()) {
            val cases = byLocation[key].orEmpty()
            if (cases.isEmpty()) continue
            val sorted = cases.sortedBy { it.start }
            val isOR = looksLikeOperatingRoom(key)
            groups.add(
                ClinicOrFacilityGroup(
                    id = "loc-$key",
                    title = displayFacilityTitle(key),
                    timeRange = timeSpan(sorted),
                    details = sorted.map { surgeryDetail(it) },
                    countStyle = if (isOR) {
                        ClinicOrFacilityGroup.CountStyle.Cases
                    } else {
                        ClinicOrFacilityGroup.CountStyle.Visits
                    },
                ),
            )
        }

        return groups
    }

    private fun surgeryBelongs(surgery: ScheduleItemUi, to: ScheduleItemUi): Boolean {
        val loc = surgery.location.trim()
        val title = to.title.trim()
        if (title.isEmpty()) return false

        if (loc.isNotEmpty()) {
            if (loc.equals(title, ignoreCase = true)) return true
            val locNorm = normalizeFacility(loc)
            val titleNorm = normalizeFacility(title)
            if (locNorm == titleNorm || locNorm.contains(titleNorm) || titleNorm.contains(locNorm)) {
                return true
            }
            if (canonicalFacility(locNorm) == canonicalFacility(titleNorm)) return true
        }

        val room = surgery.room.trim()
        if (room.isNotEmpty()) {
            val roomCanon = canonicalFacility(normalizeFacility(room))
            val titleCanon = canonicalFacility(normalizeFacility(title))
            if (roomCanon.isNotEmpty() && roomCanon == titleCanon) return true
        }
        return false
    }

    private fun surgeryDetail(item: ScheduleItemUi): ClinicOrDetailRow {
        val procedure = item.procedure.trim()
        val room = item.room.trim()
        val secondary = listOf(procedure, room).filter { it.isNotEmpty() }.joinToString(" · ")
        return ClinicOrDetailRow(
            id = item.id,
            time = displayClock(item.start),
            primary = item.title,
            secondary = secondary,
        )
    }

    private fun mergeDetails(
        primary: List<ClinicOrDetailRow>,
        secondary: List<ClinicOrDetailRow>,
    ): List<ClinicOrDetailRow> {
        val seen = primary.map { "${it.time}|${it.primary.lowercase(Locale.US)}" }.toMutableSet()
        val out = primary.toMutableList()
        for (row in secondary) {
            val key = "${row.time}|${row.primary.lowercase(Locale.US)}"
            if (seen.add(key)) out.add(row)
        }
        return out.sortedBy { it.time }
    }

    private fun parseClinicVisits(notes: String): List<ClinicOrDetailRow> {
        if (notes.isEmpty()) return emptyList()
        val regex = Regex("""(\d{1,2}:\d{2})\s+([^;]+)""")
        val rows = mutableListOf<ClinicOrDetailRow>()
        for (match in regex.findAll(notes)) {
            val time = match.groupValues[1]
            val name = match.groupValues[2].trim()
            if (name.isEmpty()) continue
            val lower = name.lowercase(Locale.US)
            if (lower.contains("desk fax") || lower.contains("kno2") || lower.startsWith("source=")) {
                continue
            }
            rows.add(
                ClinicOrDetailRow(
                    id = "visit-$time-$name",
                    time = displayClock(time),
                    primary = name,
                    secondary = "",
                ),
            )
        }
        return rows
    }

    private fun locationKey(item: ScheduleItemUi): String {
        val loc = item.location.trim()
        if (loc.isNotEmpty()) return displayFacilityTitle(loc)
        val room = item.room.trim()
        if (room.isNotEmpty()) return displayFacilityTitle(room)
        return "Surgery"
    }

    private fun displayFacilityTitle(value: String): String =
        when (canonicalFacility(normalizeFacility(value))) {
            "winter garden or" -> "Winter Garden OR"
            "apopka or" -> "Apopka OR"
            "altamonte or" -> "Altamonte OR"
            "minneola or" -> "Minneola OR"
            "winter garden clinic" -> "Winter Garden Clinic"
            "apopka clinic" -> "Apopka Clinic"
            "surgery one" -> "Surgery One"
            else -> value
        }

    private fun expandedTimeRange(facility: ScheduleItemUi, cases: List<ScheduleItemUi>): String {
        val starts = buildList {
            if (facility.start.isNotEmpty()) add(facility.start)
            cases.forEach { if (it.start.isNotEmpty()) add(it.start) }
        }
        val ends = buildList {
            if (facility.end.isNotEmpty()) add(facility.end)
            cases.forEach { if (it.end.isNotEmpty()) add(it.end) }
        }
        val first = starts.sorted().firstOrNull() ?: return facility.timeRange
        val last = ends.sorted().lastOrNull() ?: facility.end
        if (last.isEmpty()) return displayClock(first)
        return "${displayClock(first)} - ${displayClock(last)}"
    }

    private fun timeSpan(items: List<ScheduleItemUi>): String {
        val starts = items.map { it.start }.filter { it.isNotEmpty() }.sorted()
        val ends = items.map { it.end }.filter { it.isNotEmpty() }.sorted()
        val first = starts.firstOrNull() ?: return ""
        val startText = displayClock(first)
        val lastEnd = ends.lastOrNull()
        if (!lastEnd.isNullOrEmpty()) return "$startText - ${displayClock(lastEnd)}"
        val lastStart = starts.lastOrNull()
        if (lastStart != null && lastStart != first) return "$startText - ${displayClock(lastStart)}"
        return startText
    }

    private fun normalizeFacility(value: String): String =
        value
            .lowercase(Locale.US)
            .replace("-", " ")
            .replace(Regex("""\s+"""), " ")
            .trim()

    private fun canonicalFacility(normalized: String): String {
        val compact = normalized.replace(" ", "")
        if (compact.contains("ahwg") || compact == "wgd" || compact.contains("wintergardenor")) {
            return "winter garden or"
        }
        if (compact.contains("ahapop") || compact.contains("apk") || compact.contains("apopkaor")) {
            return "apopka or"
        }
        if (compact.contains("ahalt") || compact.contains("altamonteor")) {
            return "altamonte or"
        }
        if (compact.contains("ahmin") || compact.contains("minneolaor")) {
            return "minneola or"
        }
        if (compact.contains("clermont") || compact.contains("mainoffice") ||
            compact.contains("mainclinic") || compact.contains("surgeryone") ||
            normalized == "surgery one"
        ) {
            return "surgery one"
        }
        if (normalized.contains("winter garden") && normalized.contains("clinic")) {
            return "winter garden clinic"
        }
        if (normalized.contains("winter garden") && normalized.contains("or")) {
            return "winter garden or"
        }
        if (normalized.contains("apopka") && normalized.contains("clinic")) {
            return "apopka clinic"
        }
        if (normalized.contains("apopka") && normalized.contains("or")) {
            return "apopka or"
        }
        return normalized
    }

    private fun looksLikeOperatingRoom(title: String): Boolean {
        val t = title.lowercase(Locale.US)
        if (t.contains("clinic") || t.contains("surgery one")) return false
        val canon = canonicalFacility(normalizeFacility(title))
        if (canon == "surgery one") return false
        if (canon.endsWith(" or")) return true
        return t.endsWith(" or") || t.contains("-or") || t.startsWith("surgery ")
    }

    private fun displayClock(value: String): String {
        val trimmed = value.trim()
        if (trimmed.isEmpty()) return ""
        val parts = trimmed.split(":")
        val hour = parts.firstOrNull()?.toIntOrNull() ?: return trimmed
        val minute = parts.getOrNull(1)?.take(2) ?: "00"
        return "%02d:%s".format(hour, minute)
    }
}

@Composable
fun ClinicOrScheduleList(
    dayId: String,
    items: List<ScheduleItemUi>,
) {
    val groups = remember(items) { ClinicOrScheduleBuilder.groups(items) }
    var collapsedIds by remember { mutableStateOf(setOf<String>()) }

    LaunchedEffect(dayId) {
        collapsedIds = emptySet()
    }

    Column(
        modifier = Modifier.fillMaxWidth(),
        verticalArrangement = Arrangement.spacedBy(2.dp),
    ) {
        if (groups.isEmpty()) {
            Text("No clinic or hospital schedule", color = ClinicalPalette.Muted, fontSize = 13.sp)
        } else {
            groups.forEach { group ->
                ClinicOrFacilityBlock(
                    group = group,
                    isExpanded = group.id !in collapsedIds,
                    onToggle = {
                        collapsedIds = if (group.id in collapsedIds) {
                            collapsedIds - group.id
                        } else {
                            collapsedIds + group.id
                        }
                    },
                )
            }
        }
    }
}

@Composable
private fun ClinicOrFacilityBlock(
    group: ClinicOrFacilityGroup,
    isExpanded: Boolean,
    onToggle: () -> Unit,
) {
    Column(modifier = Modifier.fillMaxWidth()) {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .clickable(onClick = onToggle)
                .padding(vertical = 8.dp),
            horizontalArrangement = Arrangement.spacedBy(10.dp),
            verticalAlignment = Alignment.Top,
        ) {
            Text(
                group.timeRange.ifBlank { "—" },
                fontFamily = FontFamily.Monospace,
                fontSize = 12.sp,
                color = ClinicalPalette.Ink,
                modifier = Modifier.width(96.dp),
            )
            Text(
                group.headerTitle,
                fontWeight = FontWeight.SemiBold,
                fontSize = 14.sp,
                color = ClinicalPalette.Ink,
                modifier = Modifier.weight(1f),
            )
            Icon(
                Icons.Rounded.ExpandMore,
                contentDescription = if (isExpanded) "Collapse" else "Expand",
                tint = ClinicalPalette.Muted,
                modifier = Modifier.rotate(if (isExpanded) 0f else -90f),
            )
        }

        AnimatedVisibility(visible = isExpanded) {
            if (group.details.isEmpty()) {
                Text(
                    "No cases or visits listed",
                    color = ClinicalPalette.Muted,
                    fontSize = 12.sp,
                    modifier = Modifier.padding(start = 106.dp, bottom = 8.dp),
                )
            } else {
                Column(
                    modifier = Modifier.padding(bottom = 8.dp),
                    verticalArrangement = Arrangement.spacedBy(6.dp),
                ) {
                    group.details.forEach { row ->
                        ClinicOrDetailLine(row)
                    }
                }
            }
        }
    }
}

@Composable
private fun ClinicOrDetailLine(row: ClinicOrDetailRow) {
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.spacedBy(10.dp),
        verticalAlignment = Alignment.Top,
    ) {
        Text(
            row.time.ifBlank { "—" },
            fontFamily = FontFamily.Monospace,
            fontSize = 12.sp,
            color = ClinicalPalette.Ink,
            modifier = Modifier.width(96.dp),
        )
        Column(modifier = Modifier.weight(1f)) {
            Text(
                row.primary,
                fontWeight = FontWeight.SemiBold,
                fontSize = 14.sp,
                color = ClinicalPalette.Ink,
            )
            if (row.secondary.isNotEmpty()) {
                Text(
                    row.secondary,
                    color = ClinicalPalette.Muted,
                    fontSize = 11.sp,
                    maxLines = 1,
                )
            }
        }
    }
}
