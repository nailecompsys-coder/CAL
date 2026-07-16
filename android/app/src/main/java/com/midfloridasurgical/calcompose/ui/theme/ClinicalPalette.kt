package com.midfloridasurgical.calcompose.ui.theme

import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color

object ClinicalPalette {
    val Teal = Color(0xFF007580)
    val TealSoft = Color(0xFFC2EDE6)
    val Mint = Color(0xFFE0F7E0)
    val PageTop = Color(0xFFF0FAFA)
    val PageBottom = Color(0xFFEDFAF2)
    val Card = Color(0xFFFCFFFA)
    val Ink = Color(0xFF121F26)
    val Muted = Color(0xFF5C6E75)
    val Stroke = Color(0xFFC9DEDA)
}

@Composable
fun CALTheme(content: @Composable () -> Unit) {
    MaterialTheme(
        colorScheme = lightColorScheme(
            primary = ClinicalPalette.Teal,
            onPrimary = Color.White,
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
