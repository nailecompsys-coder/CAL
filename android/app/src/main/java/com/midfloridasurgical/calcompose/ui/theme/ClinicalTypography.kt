package com.midfloridasurgical.calcompose.ui.theme

import androidx.compose.material3.Typography
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.sp

/**
 * OR Whiteboard type — bold Roboto, generous sizes, Material 3 energy.
 * Integer sp only; no soft letterSpacing.
 */
object ClinicalTypography {
    private val Sans = FontFamily.SansSerif
    private val Mono = FontFamily.Monospace

    val largeTitle = TextStyle(
        fontFamily = Sans,
        fontSize = 34.sp,
        fontWeight = FontWeight.Bold,
        lineHeight = 40.sp,
        letterSpacing = (-0.3).sp,
    )
    val title = TextStyle(
        fontFamily = Sans,
        fontSize = 24.sp,
        fontWeight = FontWeight.Bold,
        lineHeight = 30.sp,
        letterSpacing = 0.sp,
    )
    val headline = TextStyle(
        fontFamily = Sans,
        fontSize = 18.sp,
        fontWeight = FontWeight.SemiBold,
        lineHeight = 24.sp,
        letterSpacing = 0.sp,
    )
    val headlineStrong = TextStyle(
        fontFamily = Sans,
        fontSize = 18.sp,
        fontWeight = FontWeight.Bold,
        lineHeight = 24.sp,
        letterSpacing = 0.sp,
    )
    val body = TextStyle(
        fontFamily = Sans,
        fontSize = 16.sp,
        fontWeight = FontWeight.Normal,
        lineHeight = 22.sp,
        letterSpacing = 0.sp,
    )
    val bodyMedium = TextStyle(
        fontFamily = Sans,
        fontSize = 16.sp,
        fontWeight = FontWeight.Medium,
        lineHeight = 22.sp,
        letterSpacing = 0.sp,
    )
    val rowTitle = TextStyle(
        fontFamily = Sans,
        fontSize = 16.sp,
        fontWeight = FontWeight.SemiBold,
        lineHeight = 22.sp,
        letterSpacing = 0.sp,
    )
    val rowTitleStrong = TextStyle(
        fontFamily = Sans,
        fontSize = 16.sp,
        fontWeight = FontWeight.Bold,
        lineHeight = 22.sp,
        letterSpacing = 0.sp,
    )
    val subheadline = TextStyle(
        fontFamily = Sans,
        fontSize = 15.sp,
        fontWeight = FontWeight.Normal,
        lineHeight = 20.sp,
        letterSpacing = 0.sp,
    )
    val sectionLabel = TextStyle(
        fontFamily = Sans,
        fontSize = 13.sp,
        fontWeight = FontWeight.Bold,
        lineHeight = 16.sp,
        letterSpacing = 0.4.sp,
    )
    val caption = TextStyle(
        fontFamily = Sans,
        fontSize = 13.sp,
        fontWeight = FontWeight.SemiBold,
        lineHeight = 16.sp,
        letterSpacing = 0.sp,
    )
    val captionEmphasized = TextStyle(
        fontFamily = Sans,
        fontSize = 12.sp,
        fontWeight = FontWeight.Bold,
        lineHeight = 15.sp,
        letterSpacing = 0.sp,
    )
    val badge = TextStyle(
        fontFamily = Sans,
        fontSize = 11.sp,
        fontWeight = FontWeight.Bold,
        lineHeight = 13.sp,
        letterSpacing = 0.3.sp,
    )
    val dayNumber = TextStyle(
        fontFamily = Sans,
        fontSize = 16.sp,
        fontWeight = FontWeight.Bold,
        lineHeight = 18.sp,
        letterSpacing = 0.sp,
    )
    val dayNumberSelected = TextStyle(
        fontFamily = Sans,
        fontSize = 20.sp,
        fontWeight = FontWeight.Bold,
        lineHeight = 22.sp,
        letterSpacing = 0.sp,
    )
    val monoCaption = TextStyle(
        fontFamily = Mono,
        fontSize = 12.sp,
        fontWeight = FontWeight.SemiBold,
        lineHeight = 16.sp,
        letterSpacing = 0.sp,
    )
    val monoTitle = TextStyle(
        fontFamily = Mono,
        fontSize = 22.sp,
        fontWeight = FontWeight.Bold,
        lineHeight = 26.sp,
        letterSpacing = 0.sp,
    )
    val monoRow = TextStyle(
        fontFamily = Mono,
        fontSize = 15.sp,
        fontWeight = FontWeight.Bold,
        lineHeight = 20.sp,
        letterSpacing = 0.sp,
    )
    val monoChip = TextStyle(
        fontFamily = Mono,
        fontSize = 12.sp,
        fontWeight = FontWeight.Bold,
        lineHeight = 14.sp,
        letterSpacing = 0.sp,
    )

    val material: Typography = Typography(
        displayLarge = largeTitle,
        displayMedium = title,
        displaySmall = title,
        headlineLarge = title,
        headlineMedium = headlineStrong,
        headlineSmall = headline,
        titleLarge = headlineStrong,
        titleMedium = rowTitleStrong,
        titleSmall = rowTitle,
        bodyLarge = bodyMedium,
        bodyMedium = body,
        bodySmall = caption,
        labelLarge = rowTitleStrong,
        labelMedium = caption,
        labelSmall = badge,
    )
}
