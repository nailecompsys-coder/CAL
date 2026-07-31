package com.midfloridasurgical.calcompose.ui.theme

import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.sp

/**
 * Clinical Trust type scale — mirrors iOS `ClinicalTypography` in CALNativeComponents.swift.
 */
object ClinicalTypography {
    val largeTitle = TextStyle(
        fontSize = 32.sp,
        fontWeight = FontWeight.Bold,
        lineHeight = 38.sp,
    )
    val headline = TextStyle(
        fontSize = 17.sp,
        fontWeight = FontWeight.SemiBold,
        lineHeight = 22.sp,
    )
    val headlineStrong = TextStyle(
        fontSize = 17.sp,
        fontWeight = FontWeight.Black,
        lineHeight = 22.sp,
    )
    val rowTitle = TextStyle(
        fontSize = 15.sp,
        fontWeight = FontWeight.SemiBold,
        lineHeight = 20.sp,
    )
    val rowTitleStrong = TextStyle(
        fontSize = 15.sp,
        fontWeight = FontWeight.Bold,
        lineHeight = 20.sp,
    )
    val sectionLabel = TextStyle(
        fontSize = 12.sp,
        fontWeight = FontWeight.Black,
        lineHeight = 16.sp,
        letterSpacing = 0.2.sp,
    )
    val caption = TextStyle(
        fontSize = 12.sp,
        fontWeight = FontWeight.SemiBold,
        lineHeight = 16.sp,
    )
    val captionEmphasized = TextStyle(
        fontSize = 11.sp,
        fontWeight = FontWeight.SemiBold,
        lineHeight = 14.sp,
    )
    val badge = TextStyle(
        fontSize = 10.sp,
        fontWeight = FontWeight.Black,
        lineHeight = 12.sp,
    )
    val monoCaption = TextStyle(
        fontSize = 12.sp,
        fontWeight = FontWeight.SemiBold,
        fontFamily = FontFamily.Monospace,
        lineHeight = 16.sp,
    )
    val monoChip = TextStyle(
        fontSize = 11.sp,
        fontWeight = FontWeight.SemiBold,
        fontFamily = FontFamily.Monospace,
        lineHeight = 14.sp,
    )
}
