package com.midfloridasurgical.calcompose.ui.theme

import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color

/**
 * Clinical Trust tokens for Compose — hex values match iOS `Images.xcassets/Clinical*.colorset`.
 * Call sites must use these names; never scatter raw Color(0x…) in UI.
 */
object ClinicalPalette {
    val Teal = Color(0xFF007580)
    val TealSoft = Color(0xFFC2EDE6)
    val Mint = Color(0xFFE0F7E0)
    val PageTop = Color(0xFFF0FAFA)
    val PageMiddle = Color(0xFFFCFFFA)
    val PageBottom = Color(0xFFEDFAF2)
    val Card = Color(0xFFFCFFFA)
    val CardStrong = Color(0xFFFFFFF7)
    val Ink = Color(0xFF121F26)
    val Muted = Color(0xFF5C6E75)
    val Stroke = Color(0xFFC9DEDA)
    val OnTeal = Color(0xFFFFFFFF)
    val Amber = Color(0xFFFFEBBD)
    val PorcelainChip = Color(0xFFF7FAF2)
    val ScrubInk = Color(0xFF1A6B4C)
    val Meeting = Color(0xFFDCC9F5)
    val Block = Color(0xFFFAB8B8)
    val Shadow = Color(0xFF143D3D)
    /** Readable status/warning text — Amber is a soft fill, not for type (iOS `warningText`). */
    val WarningText = Color(0xFFFF9500)
    /** Denied / destructive status (iOS system `.red` / Clinical Trust danger). */
    val Denied = Color(0xFFDC3545)
    /** Call coverage initials / strike (iOS `.red`). */
    val CoverageRed = Color(0xFFDC3545)
    val Transparent = Color.Transparent
}

@Composable
fun CALTheme(content: @Composable () -> Unit) {
    MaterialTheme(
        colorScheme = lightColorScheme(
            primary = ClinicalPalette.Teal,
            onPrimary = ClinicalPalette.OnTeal,
            secondary = ClinicalPalette.Muted,
            background = ClinicalPalette.PageTop,
            surface = ClinicalPalette.Card,
            onSurface = ClinicalPalette.Ink,
            surfaceVariant = ClinicalPalette.TealSoft,
            outline = ClinicalPalette.Stroke,
        ),
        content = content,
    )
}
